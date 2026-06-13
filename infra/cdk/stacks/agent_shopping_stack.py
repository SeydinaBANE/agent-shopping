from __future__ import annotations

import json
from typing import Any

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_opensearchserverless as opss,
    aws_ssm as ssm,
    aws_wafv2 as wafv2,
)
from constructs import Construct


APP_NAME = "agent-shopping"
MODEL_SONNET = "anthropic.claude-3-5-sonnet-20240620-v1:0"
MODEL_HAIKU = "anthropic.claude-3-haiku-20240307-v1:0"
MODEL_EMBEDDING = "amazon.titan-embed-text-v2:0"


class AgentShoppingStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = self._create_vpc()
        lambda_role = self._create_lambda_role()
        log_group = self._create_log_group()

        orchestrator = self._create_lambda(vpc, lambda_role)
        log_group.grant_write(lambda_role)

        http_api = self._create_api_gateway(orchestrator)
        self._create_waf(http_api)
        self._create_opensearch_serverless(lambda_role)
        self._create_ssm_parameters()
        self._create_monitoring(orchestrator)

        cdk.CfnOutput(self, "ApiGatewayUrl", value=http_api.url or "")
        cdk.CfnOutput(self, "LambdaFunctionName", value=orchestrator.function_name)

    # ----- VPC -----

    def _create_vpc(self) -> ec2.Vpc:
        return ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            restrict_default_security_group=True,
        )

    # ----- IAM -----

    def _create_lambda_role(self) -> iam.Role:
        role = iam.Role(
            self,
            "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{MODEL_SONNET}",
                    f"arn:aws:bedrock:{self.region}::foundation-model/{MODEL_HAIKU}",
                    f"arn:aws:bedrock:{self.region}::foundation-model/{MODEL_EMBEDDING}",
                ],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssm:GetParametersByPath",
                    "ssm:GetParameter",
                    "ssm:GetParameters",
                ],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/{APP_NAME}/tenants/*",
                ],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "aoss:APIAccessAll",
                    "aoss:CreateIndex",
                    "aoss:ReadDocument",
                    "aoss:WriteDocument",
                ],
                resources=["*"],
            )
        )

        return role

    # ----- Lambda -----

    def _create_log_group(self) -> logs.LogGroup:
        return logs.LogGroup(
            self,
            "LambdaLogGroup",
            log_group_name=f"/aws/lambda/{APP_NAME}",
            retention=logs.RetentionDays.ONE_WEEK,
        )

    def _create_lambda(self, vpc: ec2.Vpc, role: iam.Role) -> lambda_.DockerImageFunction:
        return lambda_.DockerImageFunction(
            self,
            "Orchestrator",
            code=lambda_.DockerImageCode.from_image_asset("../../", file="Dockerfile"),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            memory_size=512,
            timeout=Duration.seconds(30),
            environment={
                "BEDROCK_MODEL_ID": MODEL_SONNET,
                "BEDROCK_FAST_MODEL_ID": MODEL_HAIKU,
                "BEDROCK_EMBEDDING_MODEL": MODEL_EMBEDDING,
                "BEDROCK_TEMPERATURE": "0.3",
                "BEDROCK_MAX_TOKENS": "1024",
                "OPENSEARCH_HOST": self._opensearch_host(),
                "OPENSEARCH_PORT": "9200",
                "OPENSEARCH_INDEX_PREFIX": APP_NAME,
                "MOCK_API": "false",
            },
            role=role,
        )

    # ----- API Gateway -----

    def _create_api_gateway(
        self, orchestrator: lambda_.DockerImageFunction
    ) -> apigwv2.HttpApi:
        http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name=APP_NAME,
            description="Agent Shopping — assistant IA conversationnel e-commerce",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Api-Key",
                ],
                max_age=Duration.hours(1),
            ),
        )

        lambda_integration = apigwv2_integrations.HttpLambdaIntegration(
            "LambdaIntegration",
            handler=orchestrator,
        )

        http_api.add_routes(
            path="/assistant/chat",
            methods=[apigwv2.HttpMethod.POST],
            integration=lambda_integration,
        )
        http_api.add_routes(
            path="/health",
            methods=[apigwv2.HttpMethod.GET],
            integration=lambda_integration,
        )

        return http_api

    # ----- WAF -----

    def _create_waf(self, http_api: apigwv2.HttpApi) -> None:
        web_acl = wafv2.CfnWebACL(
            self,
            "WebACL",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            scope="REGIONAL",
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name=f"{APP_NAME}-waf",
                sampled_requests_enabled=True,
            ),
            rules=[
                self._rate_limit_rule(),
                self._managed_rule("AWSManagedRulesCommonRuleSet", 1),
                self._managed_rule("AWSManagedRulesSQLiRuleSet", 10),
                self._managed_rule("AWSManagedRulesKnownBadInputsRuleSet", 20),
            ],
        )

        stage_name = http_api.default_stage.stage_name if http_api.default_stage else "$default"
        wafv2.CfnWebACLAssociation(
            self,
            "WebACLAssociation",
            web_acl_arn=web_acl.attr_arn,
            resource_arn=f"arn:aws:apigateway:{self.region}::/apis/{http_api.http_api_id}/stages/{stage_name}",
        )

    def _rate_limit_rule(self) -> dict[str, Any]:
        return {
            "name": "RateLimit",
            "priority": 0,
            "action": {"block": {}},
            "statement": {
                "rateBasedStatement": {
                    "limit": 100,
                    "aggregateKeyType": "IP",
                }
            },
            "visibilityConfig": {
                "cloudWatchMetricsEnabled": True,
                "metricName": f"{APP_NAME}-rate-limit",
                "sampledRequestsEnabled": True,
            },
        }

    def _managed_rule(self, name: str, priority: int) -> dict[str, Any]:
        return {
            "name": name,
            "priority": priority,
            "overrideAction": {"none": {}},
            "statement": {
                "managedRuleGroupStatement": {
                    "vendorName": "AWS",
                    "name": name,
                }
            },
            "visibilityConfig": {
                "cloudWatchMetricsEnabled": True,
                "metricName": f"{APP_NAME}-{name.lower()}",
                "sampledRequestsEnabled": True,
            },
        }

    # ----- OpenSearch Serverless -----

    def _opensearch_host(self) -> str:
        return f"https://{self.stack_name.lower()}.{self.region}.aoss.amazonaws.com"

    def _create_opensearch_serverless(self, lambda_role: iam.Role) -> None:
        collection = opss.CfnCollection(
            self,
            "SearchCollection",
            name=f"{APP_NAME}-rag",
            type="SEARCH",
            description="Agent Shopping — RAG et cache sémantique",
        )

        opss.CfnSecurityPolicy(
            self,
            "EncryptionPolicy",
            name=f"{APP_NAME}-encryption",
            type="encryption",
            policy=json.dumps({
                "Rules": [
                    {
                        "Resource": [f"collection/{APP_NAME}-rag"],
                        "ResourceType": "collection",
                    }
                ],
                "AWSOwnedKey": True,
            }),
        )

        opss.CfnSecurityPolicy(
            self,
            "NetworkPolicy",
            name=f"{APP_NAME}-network",
            type="network",
            policy=json.dumps({
                "Rules": [
                    {
                        "Resource": [f"collection/{APP_NAME}-rag"],
                        "ResourceType": "collection",
                    }
                ],
                "AllowFromPublic": True,
            }),
        )

        opss.CfnAccessPolicy(
            self,
            "DataAccessPolicy",
            name=f"{APP_NAME}-data-access",
            type="data",
            policy=json.dumps([
                {
                    "Rules": [
                        {
                            "Resource": [f"collection/{APP_NAME}-rag"],
                            "ResourceType": "collection",
                            "Permission": [
                                "aoss:CreateCollectionItems",
                                "aoss:DescribeCollectionItems",
                            ],
                        },
                        {
                            "Resource": [f"index/{APP_NAME}-rag/*"],
                            "ResourceType": "index",
                            "Permission": [
                                "aoss:CreateIndex",
                                "aoss:ReadDocument",
                                "aoss:WriteDocument",
                                "aoss:DeleteDocument",
                                "aoss:DescribeIndex",
                            ],
                        },
                    ],
                    "Principal": [
                        lambda_role.role_arn,
                    ],
                }
            ]),
        )

        collection.add_dependency(encryption_policy)
        collection.add_dependency(network_policy)

    # ----- SSM -----

    def _create_ssm_parameters(self) -> None:
        ssm.StringParameter(
            self,
            "DefaultTenantConfig",
            parameter_name=f"/{APP_NAME}/tenants/default/config",
            string_value=json.dumps({
                "tenant_id": "default",
                "name": "Default Tenant",
                "public_key_jwks_uri": "",
                "api_base_url": "",
                "api_auth_header": "X-Api-Key",
                "endpoints": {
                    "search_products": "/products/search",
                    "product_detail": "/products/{produit_id}",
                    "check_inventory": "/products/{produit_id}/stock",
                    "user_history": "/users/{client_id}/orders",
                    "add_to_cart": "/cart",
                    "place_order": "/orders",
                    "track_order": "/orders/{commande_id}",
                },
                "brand": {
                    "primary_color": "#6C5CE7",
                    "name": "Agent Shopping",
                },
                "llm_config": {
                    "model": MODEL_SONNET,
                    "temperature": 0.3,
                    "max_tokens": 1024,
                },
            }),
        )

    # ----- Monitoring -----

    def _create_monitoring(self, orchestrator: lambda_.DockerImageFunction) -> None:
        dashboard = cloudwatch.Dashboard(
            self,
            "Dashboard",
            dashboard_name=f"{APP_NAME}-dashboard",
        )

        error_metric = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": orchestrator.function_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )

        latency_metric = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Duration",
            dimensions_map={"FunctionName": orchestrator.function_name},
            statistic="p95",
            period=Duration.minutes(5),
        )

        invocations_metric = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Invocations",
            dimensions_map={"FunctionName": orchestrator.function_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )

        dashboard.add_widgets(
            cloudwatch.Row(
                cloudwatch.GraphWidget(
                    title="Invocations & Erreurs",
                    left=[invocations_metric],
                    right=[error_metric],
                ),
                cloudwatch.GraphWidget(
                    title="Latence (p95)",
                    left=[latency_metric],
                ),
            )
        )

        cloudwatch.Alarm(
            self,
            "HighErrorRate",
            metric=error_metric,
            threshold=5,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            alarm_description="Error rate > 5 sur 10 min",
        )

        cloudwatch.Alarm(
            self,
            "HighLatency",
            metric=latency_metric,
            threshold=4000,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            alarm_description="Latence p95 > 4s",
        )
