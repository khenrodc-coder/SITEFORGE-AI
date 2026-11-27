-- SiteForge AI database schema (MySQL 8+).
-- Run once in MySQL Workbench or the mysql command line. It is safe to run again.
--
-- After running it, create a dedicated account for SiteForge (do not use root).
-- Replace the password, then put the same values in your .env file:
--
--   CREATE USER 'siteforge'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
--   GRANT SELECT, INSERT, UPDATE, DELETE ON siteforge_ai.* TO 'siteforge'@'localhost';
--   FLUSH PRIVILEGES;
--
-- Websites with pictures can be several megabytes. MySQL 8 accepts 64 MB by default
-- (max_allowed_packet), which is plenty.

CREATE DATABASE IF NOT EXISTS siteforge_ai
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE siteforge_ai;

-- Future module: user accounts. Projects already reference it so no redesign is needed later.
CREATE TABLE IF NOT EXISTS users (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email         VARCHAR(255)    NOT NULL,
  password_hash VARCHAR(255)    NOT NULL,
  display_name  VARCHAR(100)    NOT NULL,
  created_at    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB;

-- user_id is NULL while the MVP runs without login.
CREATE TABLE IF NOT EXISTS projects (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     BIGINT UNSIGNED NULL,
  name        VARCHAR(150)    NOT NULL,
  description TEXT            NULL,
  category    VARCHAR(50)     NOT NULL DEFAULT 'business',
  status      ENUM('draft','generated','archived') NOT NULL DEFAULT 'draft',
  created_at  TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_projects_user (user_id),
  KEY idx_projects_updated (updated_at),
  CONSTRAINT fk_projects_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- One row per generation (history). config_json holds the validated website configuration.
CREATE TABLE IF NOT EXISTS generated_websites (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  version       INT UNSIGNED    NOT NULL DEFAULT 1,
  prompt        TEXT            NOT NULL,
  config_json   JSON            NOT NULL,
  model_name    VARCHAR(100)    NULL,
  status        ENUM('success','failed') NOT NULL DEFAULT 'success',
  error_message VARCHAR(500)    NULL,
  created_at    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_generated_project_version (project_id, version),
  KEY idx_generated_created (created_at),
  CONSTRAINT fk_generated_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Design choices for a project (one row per project).
CREATE TABLE IF NOT EXISTS project_settings (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id    BIGINT UNSIGNED NOT NULL,
  design_style  VARCHAR(50)     NOT NULL DEFAULT 'modern',
  color_scheme  VARCHAR(50)     NOT NULL DEFAULT 'blue',
  primary_color CHAR(7)         NOT NULL DEFAULT '#2563eb',
  font_heading  VARCHAR(100)    NOT NULL DEFAULT 'Space Grotesk',
  font_body     VARCHAR(100)    NOT NULL DEFAULT 'DM Sans',
  created_at    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_settings_project (project_id),
  CONSTRAINT fk_settings_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE=InnoDB;
