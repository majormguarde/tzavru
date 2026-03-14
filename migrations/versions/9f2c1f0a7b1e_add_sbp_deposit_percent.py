"""Add SBP deposit percent to site settings

Revision ID: 9f2c1f0a7b1e
Revises: 4c0b1d9a2f4e
Create Date: 2026-03-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f2c1f0a7b1e'
down_revision = '4c0b1d9a2f4e'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'site_settings' not in existing_tables:
        return

    cols = {c['name'] for c in inspector.get_columns('site_settings')}
    if 'sbp_deposit_percent' not in cols:
        op.add_column('site_settings', sa.Column('sbp_deposit_percent', sa.Integer(), server_default='30', nullable=True))
        op.execute("UPDATE site_settings SET sbp_deposit_percent = 30 WHERE sbp_deposit_percent IS NULL")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'site_settings' not in existing_tables:
        return

    cols = {c['name'] for c in inspector.get_columns('site_settings')}
    if 'sbp_deposit_percent' in cols:
        op.drop_column('site_settings', 'sbp_deposit_percent')
