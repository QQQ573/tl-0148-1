"""init schema

Revision ID: 0001_init
Revises: 
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM


# revision identifiers, used by Alembic.
revision: str = '0001_init'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_role_enum = ENUM('workshop_manager', 'master', 'finance', 'student', name='user_role_enum', create_type=True)
    user_role_enum.create(op.get_bind(), checkfirst=True)

    booking_status_enum = ENUM('draft', 'pending_quota', 'pending_signature', 'pending_payment', 'confirmed', 'rejected', name='booking_status_enum', create_type=True)
    booking_status_enum.create(op.get_bind(), checkfirst=True)

    clay_type_enum = ENUM('gaobai_ni', 'hongtao', 'xianwei_ni', name='clay_type_enum', create_type=True)
    clay_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(length=50), nullable=False, unique=True),
        sa.Column('email', sa.String(length=100), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=100), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('role', user_role_enum, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=False)
    op.create_index('ix_users_email', 'users', ['email'], unique=False)
    op.create_index('ix_users_role', 'users', ['role'], unique=False)

    op.create_table(
        'master_classes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('master_id', sa.Integer(), nullable=False),
        sa.Column('class_date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.String(length=10), nullable=False),
        sa.Column('end_time', sa.String(length=10), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=False, server_default='8'),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('class_no', sa.Integer(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['master_id'], ['users.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('year', 'month', 'class_no', name='uq_year_month_class_no'),
    )
    op.create_index('ix_master_classes_master_id', 'master_classes', ['master_id'])
    op.create_index('ix_master_classes_class_date', 'master_classes', ['class_date'])
    op.create_index('ix_master_classes_year', 'master_classes', ['year'])
    op.create_index('ix_master_classes_month', 'master_classes', ['month'])
    op.create_index('ix_master_classes_class_no', 'master_classes', ['class_no'])

    op.create_table(
        'clay_quotas',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('master_class_id', sa.Integer(), nullable=False),
        sa.Column('clay_type', clay_type_enum, nullable=False),
        sa.Column('total_kg', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('used_kg', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['master_class_id'], ['master_classes.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('master_class_id', 'clay_type', name='uq_class_clay_type'),
    )
    op.create_index('ix_clay_quotas_master_class_id', 'clay_quotas', ['master_class_id'])

    op.create_table(
        'bookings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('booking_no', sa.String(length=32), nullable=False, unique=True),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('master_class_id', sa.Integer(), nullable=False),
        sa.Column('class_year', sa.Integer(), nullable=False),
        sa.Column('class_month', sa.Integer(), nullable=False),
        sa.Column('status', booking_status_enum, nullable=False, server_default='draft'),
        sa.Column('gaobai_ni_kg', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'),
        sa.Column('hongtao_kg', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'),
        sa.Column('xianwei_ni_kg', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'),
        sa.Column('student_remark', sa.Text(), nullable=True),
        sa.Column('quota_remark', sa.Text(), nullable=True),
        sa.Column('reject_reason', sa.Text(), nullable=True),
        sa.Column('signed_by_id', sa.Integer(), nullable=True),
        sa.Column('signed_at', sa.DateTime(), nullable=True),
        sa.Column('paid_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_alerted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['master_class_id'], ['master_classes.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['signed_by_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_bookings_booking_no', 'bookings', ['booking_no'], unique=True)
    op.create_index('ix_bookings_student_id', 'bookings', ['student_id'])
    op.create_index('ix_bookings_master_class_id', 'bookings', ['master_class_id'])
    op.create_index('ix_bookings_status', 'bookings', ['status'])
    op.create_index('ix_bookings_last_updated_at', 'bookings', ['last_updated_at'])
    op.create_index('ix_booking_student_month_status', 'bookings', ['student_id', 'class_year', 'class_month', 'status'])

    op.create_table(
        'booking_status_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('from_status', booking_status_enum, nullable=True),
        sa.Column('to_status', booking_status_enum, nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_booking_status_logs_booking_id', 'booking_status_logs', ['booking_id'])
    op.create_index('ix_booking_status_logs_operator_id', 'booking_status_logs', ['operator_id'])

    op.create_table(
        'attachments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('minio_object_key', sa.String(length=500), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_attachments_booking_id', 'attachments', ['booking_id'])
    op.create_index('ix_attachments_uploaded_by_id', 'attachments', ['uploaded_by_id'])


def downgrade() -> None:
    op.drop_table('attachments')
    op.drop_table('booking_status_logs')
    op.drop_table('bookings')
    op.drop_table('clay_quotas')
    op.drop_table('master_classes')
    op.drop_table('users')

    booking_status_enum = ENUM(name='booking_status_enum')
    booking_status_enum.drop(op.get_bind(), checkfirst=True)
    clay_type_enum = ENUM(name='clay_type_enum')
    clay_type_enum.drop(op.get_bind(), checkfirst=True)
    user_role_enum = ENUM(name='user_role_enum')
    user_role_enum.drop(op.get_bind(), checkfirst=True)
