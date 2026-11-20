"""telegram account linking

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20 04:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add telegram_user_id and telegram_username to users
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('telegram_user_id', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('telegram_username', sa.String(length=100), nullable=True))
        batch_op.create_index('ix_users_telegram_user_id', ['telegram_user_id'], unique=True)

    # 2. Create telegram_link_codes table
    op.create_table(
        'telegram_link_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('telegram_link_codes') as batch_op:
        batch_op.create_index('ix_telegram_link_codes_code', ['code'], unique=True)
        batch_op.create_index('ix_telegram_link_codes_user_id', ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('telegram_link_codes') as batch_op:
        batch_op.drop_index('ix_telegram_link_codes_user_id')
        batch_op.drop_index('ix_telegram_link_codes_code')
    op.drop_table('telegram_link_codes')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_index('ix_users_telegram_user_id')
        batch_op.drop_column('telegram_username')
        batch_op.drop_column('telegram_user_id')
