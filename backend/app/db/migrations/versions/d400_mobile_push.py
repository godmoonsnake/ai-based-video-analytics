"""Track freshness of guard phone registrations."""
from alembic import op
import sqlalchemy as sa

revision = "d400_mobile_push"
down_revision = "d300_zone_pilot"
branch_labels = depends_on = None


def upgrade():
    op.add_column("pilot_contact", sa.Column("last_registered_at", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("pilot_contact", "last_registered_at")
