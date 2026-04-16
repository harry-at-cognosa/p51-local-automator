from sqlalchemy.orm import declarative_base

Base = declarative_base()

from .models import (
    ApiGroups, User, ApiSettings, GroupSettings,
    WorkflowTypes, UserWorkflows, WorkflowRuns, WorkflowSteps, WorkflowArtifacts,
    Conversations, ConversationMessages,
)
