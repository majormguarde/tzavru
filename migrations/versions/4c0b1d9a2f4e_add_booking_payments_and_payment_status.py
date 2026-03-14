"""Add booking payments and payment status

Revision ID: 4c0b1d9a2f4e
Revises: c31c1b7e0a2d
Create Date: 2026-03-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4c0b1d9a2f4e'
down_revision = 'c31c1b7e0a2d'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'booking' in existing_tables:
        existing_booking_cols = {c['name'] for c in inspector.get_columns('booking')}
        if 'payment_status' not in existing_booking_cols:
            op.add_column('booking', sa.Column('payment_status', sa.String(length=20), server_default='unpaid', nullable=True))
            op.execute("UPDATE booking SET payment_status = 'unpaid' WHERE payment_status IS NULL")

    if 'booking_payment' not in existing_tables:
        op.create_table(
            'booking_payment',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('booking_id', sa.Integer(), nullable=False),
            sa.Column('provider', sa.String(length=30), server_default='sbp_phone', nullable=False),
            sa.Column('provider_payment_id', sa.String(length=80), nullable=True),
            sa.Column('kind', sa.String(length=20), server_default='booking', nullable=False),
            sa.Column('status', sa.String(length=30), server_default='requested', nullable=False),
            sa.Column('amount', sa.Float(), server_default='0', nullable=False),
            sa.Column('currency', sa.String(length=3), server_default='RUB', nullable=False),
            sa.Column('confirmation_url', sa.Text(), nullable=True),
            sa.Column('idempotency_key', sa.String(length=64), nullable=True),
            sa.Column('paid_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('raw_response', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['booking_id'], ['booking.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_booking_payment_booking_id'), 'booking_payment', ['booking_id'], unique=False)
        op.create_index(op.f('ix_booking_payment_idempotency_key'), 'booking_payment', ['idempotency_key'], unique=False)
        op.create_index(op.f('ix_booking_payment_provider_payment_id'), 'booking_payment', ['provider_payment_id'], unique=True)
        op.create_index(op.f('ix_booking_payment_status'), 'booking_payment', ['status'], unique=False)
    else:
        try:
            existing_indexes = {idx['name'] for idx in inspector.get_indexes('booking_payment')}
        except Exception:
            existing_indexes = set()

        for ix_name, cols, unique in [
            (op.f('ix_booking_payment_booking_id'), ['booking_id'], False),
            (op.f('ix_booking_payment_idempotency_key'), ['idempotency_key'], False),
            (op.f('ix_booking_payment_provider_payment_id'), ['provider_payment_id'], True),
            (op.f('ix_booking_payment_status'), ['status'], False),
        ]:
            if ix_name not in existing_indexes:
                op.create_index(ix_name, 'booking_payment', cols, unique=unique)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'booking_payment' in existing_tables:
        op.drop_index(op.f('ix_booking_payment_status'), table_name='booking_payment')
        op.drop_index(op.f('ix_booking_payment_provider_payment_id'), table_name='booking_payment')
        op.drop_index(op.f('ix_booking_payment_idempotency_key'), table_name='booking_payment')
        op.drop_index(op.f('ix_booking_payment_booking_id'), table_name='booking_payment')
        op.drop_table('booking_payment')

    if 'booking' in existing_tables:
        existing_booking_cols = {c['name'] for c in inspector.get_columns('booking')}
        if 'payment_status' in existing_booking_cols:
            op.drop_column('booking', 'payment_status')
