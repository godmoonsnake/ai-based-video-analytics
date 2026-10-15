"""Store floor and block explicitly, with labelled and cancellable guard shifts."""
from alembic import op
import sqlalchemy as sa

revision = "d500_guard_schedule"
down_revision = "d400_mobile_push"
branch_labels = depends_on = None


def upgrade():
    op.add_column("security_post", sa.Column("floor", sa.String(), nullable=True))
    op.add_column("security_post", sa.Column("block", sa.String(), nullable=True))
    op.add_column("shift", sa.Column("label", sa.String(), nullable=False, server_default="custom"))
    op.add_column("shift", sa.Column("cancelled_at", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("shift", "cancelled_at")
    op.drop_column("shift", "label")
    op.drop_column("security_post", "block")
    op.drop_column("security_post", "floor")
