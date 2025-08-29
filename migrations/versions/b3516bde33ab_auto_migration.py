from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3516bde33ab'
down_revision = '70ef0f230949'
branch_labels = None
depends_on = None


def upgrade():
    # --- patients ---
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('next_of_kin_phone', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('location', sa.String(length=255), nullable=True))

    # --- payments ---
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.alter_column('service_type',
               existing_type=sa.VARCHAR(length=100),
               type_=sa.Text(),
               existing_nullable=False)

    # --- pharmacy_expenses ---
    with op.batch_alter_table('pharmacy_expenses', schema=None) as batch_op:
        batch_op.drop_column('discount')

    # --- pharmacy_sales ---
    with op.batch_alter_table('pharmacy_sales', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total_price', sa.Float(), nullable=True))

    # backfill existing sales
    op.execute("""
        UPDATE pharmacy_sales ps
        SET total_price = ps.dispensed_units * m.selling_price
        FROM medicines m
        WHERE ps.medicine_id = m.id
    """)

    # now enforce NOT NULL
    with op.batch_alter_table('pharmacy_sales', schema=None) as batch_op:
        batch_op.alter_column('total_price', nullable=False)

    # --- prescriptions ---
    with op.batch_alter_table('prescriptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total_price', sa.Float(), nullable=True))

    # backfill prescriptions
    op.execute("""
        UPDATE prescriptions p
        SET total_price = p.dispensed_units * m.selling_price
        FROM medicines m
        WHERE p.medicine_id = m.id
    """)

    with op.batch_alter_table('prescriptions', schema=None) as batch_op:
        batch_op.alter_column('total_price', nullable=False)
        batch_op.alter_column('dosage',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)


def downgrade():
    # --- prescriptions ---
    with op.batch_alter_table('prescriptions', schema=None) as batch_op:
        batch_op.alter_column('dosage',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
        batch_op.drop_column('total_price')

    # --- pharmacy_sales ---
    with op.batch_alter_table('pharmacy_sales', schema=None) as batch_op:
        batch_op.drop_column('total_price')

    # --- pharmacy_expenses ---
    with op.batch_alter_table('pharmacy_expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discount', sa.Float(), nullable=True))

    # --- payments ---
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.alter_column('service_type',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=100),
               existing_nullable=False)

    # --- patients ---
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.drop_column('location')
        batch_op.drop_column('next_of_kin_phone')
