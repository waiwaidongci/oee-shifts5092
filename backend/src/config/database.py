from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,DeclarativeBase
from src.config.settings import DATABASE_URL
class Base(DeclarativeBase): pass
engine=create_engine(DATABASE_URL,pool_pre_ping=True,connect_args={'timeout':30} if DATABASE_URL.startswith('sqlite') else {})
Session=sessionmaker(bind=engine,expire_on_commit=False)
def database():
 with Session() as db: yield db
