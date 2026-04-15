"""Relational room_types API compat

Revision ID: 5a3ac3b7c0ff
Revises: 17f8ebfb2b90
Create Date: 2026-03-29 16:22:42.926779

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision = '5a3ac3b7c0ff'
down_revision = '17f8ebfb2b90'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Phase 1: Add room_type_id as nullable
    op.add_column('rooms', sa.Column('room_type_id', sa.Integer(), nullable=True))
    
    # Phase 2: Data migration mapping
    bind = op.get_bind()
    
    # Setup ad-hoc tables for reflection query
    metadata = sa.MetaData()
    rooms_table = sa.Table('rooms', metadata,
        sa.Column('id', sa.Integer),
        sa.Column('type', sa.String(50)),
        sa.Column('room_type_id', sa.Integer)
    )
    room_types_table = sa.Table('room_types', metadata,
        sa.Column('id', sa.Integer),
        sa.Column('name', sa.String(50)),
        sa.Column('description', sa.Text),
        sa.Column('is_deleted', sa.Boolean)
    )
    
    # 2.1 Extract unique 'type' values currently in rooms
    type_rows = bind.execute(sa.select(rooms_table.c.type).distinct()).fetchall()
    unique_types = [row[0] for row in type_rows if row[0]]
    
    # 2.2 Ensure they exist in room_types
    for t_name in unique_types:
        existing = bind.execute(
            sa.select(room_types_table.c.id)
            .where(room_types_table.c.name == t_name)
        ).scalar()
        
        if not existing:
            bind.execute(
                room_types_table.insert().values(
                    name=t_name, 
                    description=f"Migración automática: {t_name}", 
                    is_deleted=False
                )
            )
            
    # 2.3 Assign room_type_id to rooms table
    for t_name in unique_types:
        rt_id = bind.execute(
            sa.select(room_types_table.c.id)
            .where(room_types_table.c.name == t_name)
        ).scalar()
        if rt_id:
            bind.execute(
                rooms_table.update()
                .where(rooms_table.c.type == t_name)
                .values(room_type_id=rt_id)
            )

    # Phase 3: Enforce Nullable constraint and constraints
    op.alter_column('rooms', 'room_type_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key('fk_rooms_room_type_id', 'rooms', 'room_types', ['room_type_id'], ['id'])
    
    # Drop legacy column
    op.drop_column('rooms', 'type')


def downgrade() -> None:
    # Reverse process
    op.add_column('rooms', sa.Column('type', sa.String(length=50), nullable=True))
    
    bind = op.get_bind()
    
    metadata = sa.MetaData()
    rooms_table = sa.Table('rooms', metadata,
        sa.Column('id', sa.Integer),
        sa.Column('type', sa.String(50)),
        sa.Column('room_type_id', sa.Integer)
    )
    room_types_table = sa.Table('room_types', metadata,
        sa.Column('id', sa.Integer),
        sa.Column('name', sa.String(50))
    )
    
    room_rows = bind.execute(sa.select(rooms_table.c.id, rooms_table.c.room_type_id)).fetchall()
    for r_id, rt_id in room_rows:
        t_name = bind.execute(sa.select(room_types_table.c.name).where(room_types_table.c.id == rt_id)).scalar()
        if t_name:
            bind.execute(rooms_table.update().where(rooms_table.c.id == r_id).values(type=t_name))
            
    op.alter_column('rooms', 'type', existing_type=sa.String(length=50), nullable=False)
    op.drop_constraint('fk_rooms_room_type_id', 'rooms', type_='foreignkey')
    op.drop_column('rooms', 'room_type_id')
