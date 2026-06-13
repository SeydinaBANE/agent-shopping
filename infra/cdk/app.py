from __future__ import annotations

import aws_cdk as cdk

from stacks.agent_shopping_stack import AgentShoppingStack

app = cdk.App()

AgentShoppingStack(
    app,
    "AgentShoppingStack",
    description="Agent Shopping — assistant IA conversationnel pour le e-commerce",
    env=cdk.Environment(
        account=app.node.try_get_context("account") or cdk.Aws.ACCOUNT_ID,
        region=app.node.try_get_context("region") or cdk.Aws.REGION,
    ),
)

app.synth()
