-- SkillProof MySQL setup. The app creates its tables automatically on first run
-- (SQLAlchemy create_all), so you only need the database and user:

CREATE DATABASE IF NOT EXISTS skillproof CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'skillproof'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON skillproof.* TO 'skillproof'@'localhost';
FLUSH PRIVILEGES;

-- Then set in .env:
-- DATABASE_URL=mysql+pymysql://skillproof:choose-a-strong-password@localhost:3306/skillproof?charset=utf8mb4
