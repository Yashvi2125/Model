"""telegram bot integration

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19 06:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('trips') as batch_op:
        batch_op.add_column(sa.Column('trip_code', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('telegram_group_chat_id', sa.BigInteger(), nullable=True))
        batch_op.create_index('ix_trips_trip_code', ['trip_code'], unique=False)
        batch_op.create_index('ix_trips_telegram_group_chat_id', ['telegram_group_chat_id'], unique=False)

    with op.batch_alter_table('trip_members') as batch_op:
        batch_op.add_column(sa.Column('telegram_user_id', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('telegram_username', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('channel_origin', sa.String(length=20), server_default='web', nullable=False))
        batch_op.create_index('ix_trip_members_telegram_user_id', ['telegram_user_id'], unique=False)

    with op.batch_alter_table('messages') as batch_op:
        batch_op.add_column(sa.Column('channel', sa.String(length=20), server_default='web', nullable=False))
        batch_op.add_column(sa.Column('external_message_id', sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('messages') as batch_op:
        batch_op.drop_column('external_message_id')
        batch_op.drop_column('channel')

    with op.batch_alter_table('trip_members') as batch_op:
        batch_op.drop_index('ix_trip_members_telegram_user_id')
        batch_op.drop_column('channel_origin')
        batch_op.drop_column('telegram_username')
        batch_op.drop_column('telegram_user_id')

    with op.batch_alter_table('trips') as batch_op:
        batch_op.drop_index('ix_trips_telegram_group_chat_id')
        batch_op.drop_index('ix_trips_trip_code')
        batch_op.drop_column('telegram_group_chat_id')
        batch_op.drop_column('trip_code')
