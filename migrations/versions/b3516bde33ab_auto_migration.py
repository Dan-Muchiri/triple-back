"""Auto migration

Revision ID: b3516bde33ab
Revises: 70ef0f230949
Create Date: 2025-08-29 08:11:37.593363
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3516bde33ab'
down_revision = '70ef0f230949'
branch_labels = None
depends_on = None


def upgrade():
    # Patients: add new fields
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('next_of_kin_phone', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('location', sa.String(length=255), nullable=True))

    # Payments: widen service_type
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.alter_column('service_type',
               existing_type=sa.VARCHAR(length=100),
               type_=sa.Text(),
               existing_nullable=False)

    # Pharmacy expenses: remove discount
    with op.batch_alter_table('pharmacy_expenses', schema=None) as batch_op:
        batch_op.drop_column('discount')

    # Pharmacy sales: add total_price column (no calculation here)
    with op.batch_alter_table('pharmacy_sales', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total_price', sa.Float(), nullable=True))
        batch_op.alter_column('total_price', nullable=False)

    # Prescriptions: add total_price column (no calculation here)
    with op.batch_alter_table('prescriptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total_price', sa.Float(), nullable=True))
        batch_op.alter_column('total_price', nullable=True)  # nullable=True to match your model
        batch_op.alter_column('dosage',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)


def downgrade():
    # Prescriptions: drop added column + restore dosage
    with op.batch_alter_table('prescriptions', schema=None) as batch_op:
        batch_op.alter_column('dosage',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
        batch_op.drop_column('total_price')

    # Pharmacy sales: drop total_price
    with op.batch_alter_table('pharmacy_sales', schema=None) as batch_op:
        batch_op.drop_column('total_price')

    # Pharmacy expenses: restore discount
    with op.batch_alter_table('pharmacy_expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discount', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True))

    # Payments: shrink service_type back
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.alter_column('service_type',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=100),
               existing_nullable=False)

    # Patients: drop new fields
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.drop_column('location')
        batch_op.drop_column('next_of_kin_phone')
