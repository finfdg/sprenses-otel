"""add finance_events central event store

Revision ID: i8j9k0l1m2n3
Revises: 27cc768012cb
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'i8j9k0l1m2n3'
down_revision = '27cc768012cb'
branch_labels = None
depends_on = None


def upgrade():
    # ── finance_events tablosu ─────────────────────────────────────────────
    op.create_table(
        'finance_events',
        sa.Column('id',             sa.BigInteger(),    primary_key=True, autoincrement=True),
        sa.Column('event_date',     sa.Date(),          nullable=False),
        sa.Column('amount',         sa.Numeric(15, 2),  nullable=False),
        sa.Column('direction',      sa.SmallInteger(),  nullable=False),
        sa.Column('currency',       sa.String(3),       nullable=False, server_default='TRY'),
        sa.Column('amount_try',     sa.Numeric(15, 2),  nullable=True),

        # Kaynak referansı
        sa.Column('source_type',   sa.String(30),      nullable=False),
        sa.Column('source_id',     sa.BigInteger(),    nullable=False),

        # Denormalize görüntü alanları
        sa.Column('description',   sa.Text(),          nullable=True),
        sa.Column('bank_name',     sa.String(100),     nullable=True),
        sa.Column('account_id',    sa.Integer(),       nullable=True),
        sa.Column('iban',          sa.String(34),      nullable=True),
        sa.Column('receipt_no',    sa.String(50),      nullable=True),
        sa.Column('balance',       sa.Numeric(15, 2),  nullable=True),
        sa.Column('payment_method',sa.String(50),      nullable=True),
        sa.Column('match_number',  sa.Integer(),       nullable=True),
        sa.Column('check_no',      sa.String(50),      nullable=True),
        sa.Column('event_status',  sa.String(20),      nullable=True),
        sa.Column('vendor_code',   sa.String(50),      nullable=True),
        sa.Column('tag_note',      sa.Text(),          nullable=True),
        sa.Column('tag_source',    sa.String(20),      nullable=True),

        # FK referansları
        sa.Column('bank_account_id', sa.Integer(),
                  sa.ForeignKey('bank_accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('vendor_id',       sa.Integer(),
                  sa.ForeignKey('vendors.id',        ondelete='SET NULL'), nullable=True),
        sa.Column('category_id',     sa.Integer(),
                  sa.ForeignKey('transaction_categories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('category_name',   sa.String(100),  nullable=True),
        sa.Column('category_color',  sa.String(20),   nullable=True),

        # Eşleştirme
        sa.Column('is_realized',  sa.Boolean(),        nullable=False, server_default='false'),
        sa.Column('is_matched',   sa.Boolean(),        nullable=False, server_default='false'),
        sa.Column('matched_event_id', sa.BigInteger(),
                  sa.ForeignKey('finance_events.id',  ondelete='SET NULL'), nullable=True),

        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at',  sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Unique constraint
    op.create_unique_constraint(
        'uq_finance_events_source',
        'finance_events',
        ['source_type', 'source_id'],
    )

    # İndeksler
    op.create_index('idx_fe_date',         'finance_events', ['event_date'])
    op.create_index('idx_fe_date_dir',     'finance_events', ['event_date', 'direction'])
    op.create_index('idx_fe_source',       'finance_events', ['source_type', 'source_id'])
    op.create_index('idx_fe_bank_account', 'finance_events', ['bank_account_id'])
    op.create_index('idx_fe_vendor',       'finance_events', ['vendor_id'])
    op.create_index('idx_fe_category',     'finance_events', ['category_id'])
    op.create_index('idx_fe_matched',      'finance_events', ['is_matched'])

    # ── vendor_balances materialized view ─────────────────────────────────
    # Cari net borç hesabını her sorguda yapmak yerine önceden hesaplar.
    # REFRESH CONCURRENTLY ile lock almadan güncellenebilir.
    op.execute("""
        CREATE MATERIALIZED VIEW vendor_balances AS
        SELECT
            v.id                                            AS vendor_id,
            v.hesap_kodu,
            v.hesap_adi,
            COALESCE(SUM(vt.borc),   0)                    AS total_borc,
            COALESCE(SUM(vt.alacak), 0)                    AS total_alacak,
            COALESCE(SUM(vt.alacak), 0) - COALESCE(SUM(vt.borc), 0) AS net_debt,
            COUNT(*) FILTER (
                WHERE vt.payment_due_date IS NOT NULL
                  AND vt.alacak > 0
                  AND vt.match_number IS NULL
            )                                               AS pending_invoice_count,
            COALESCE(SUM(vt.alacak) FILTER (
                WHERE vt.payment_due_date IS NOT NULL
                  AND vt.alacak > 0
                  AND vt.match_number IS NULL
            ), 0)                                           AS pending_invoice_amount
        FROM vendors v
        LEFT JOIN vendor_transactions vt ON vt.vendor_id = v.id
        GROUP BY v.id, v.hesap_kodu, v.hesap_adi
        WITH DATA;
    """)

    op.execute("""
        CREATE UNIQUE INDEX idx_vb_vendor_id
        ON vendor_balances (vendor_id);
    """)

    op.execute("""
        CREATE INDEX idx_vb_net_debt
        ON vendor_balances (net_debt DESC);
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS vendor_balances")
    op.drop_index('idx_fe_matched',      'finance_events')
    op.drop_index('idx_fe_category',     'finance_events')
    op.drop_index('idx_fe_vendor',       'finance_events')
    op.drop_index('idx_fe_bank_account', 'finance_events')
    op.drop_index('idx_fe_source',       'finance_events')
    op.drop_index('idx_fe_date_dir',     'finance_events')
    op.drop_index('idx_fe_date',         'finance_events')
    op.drop_constraint('uq_finance_events_source', 'finance_events')
    op.drop_table('finance_events')
