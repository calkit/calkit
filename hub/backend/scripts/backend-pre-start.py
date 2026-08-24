from app import db

if __name__ == "__main__":
    db.pre_start(db.engine)
