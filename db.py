# db.py
from sqlalchemy import create_engine, Column, Integer, String, Text, Float
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = "sqlite:///worlds.db"

Base = declarative_base()
engine = create_engine(DB_PATH, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(bind=engine)


class World(Base):
    __tablename__ = "worlds"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True)
    data = Column(Text)       # JSON 字符串
    created_at = Column(Float)


# 初始化数据库（建表）
def init_db():
    Base.metadata.create_all(bind=engine)
