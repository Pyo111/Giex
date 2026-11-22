-- =====================================================================
-- GIEX Builders Database Management System
-- Database Schema (MySQL 8.0+)
-- Entities: WORKER, PROJECT, ASSIGNMENT, ATTENDANCE (+ PROJECT_FILE)
-- =====================================================================

CREATE DATABASE IF NOT EXISTS giex_builders
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE giex_builders;

-- ---------------------------------------------------------------------
-- ADMIN: sign-in accounts for the browser interface
-- The Flask app creates this table automatically on first run and seeds a
-- default administrator (username: admin, password: admin123).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin (
    admin_id       INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    username       VARCHAR(50)   NOT NULL,
    password_hash  VARCHAR(255)  NOT NULL,          -- werkzeug password hash
    full_name      VARCHAR(100)  NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (admin_id),
    UNIQUE KEY uq_admin_username (username)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- WORKER: one record per construction worker
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS worker (
    worker_id    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    first_name   VARCHAR(50)   NOT NULL,
    last_name    VARCHAR(50)   NOT NULL,
    role         VARCHAR(50)   NOT NULL,          -- e.g. Mason, Carpenter, Foreman
    worker_rate  DECIMAL(10,2) NOT NULL,          -- daily rate (PHP / 8-hr day)
    PRIMARY KEY (worker_id),
    CONSTRAINT chk_worker_rate CHECK (worker_rate >= 0)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- PROJECT: one record per construction project
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project (
    project_id    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    project_name  VARCHAR(150)  NOT NULL,
    location      VARCHAR(200)  NOT NULL,
    start_date    DATE          NOT NULL,
    end_date      DATE          NULL,             -- NULL = ongoing
    PRIMARY KEY (project_id),
    CONSTRAINT chk_project_dates CHECK (end_date IS NULL OR end_date >= start_date)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- ASSIGNMENT: resolves the M:N between WORKER and PROJECT
--   Worker  1 : M  Assignment
--   Project 1 : M  Assignment
--   Rule: a worker may have only ONE ongoing assignment. Once the project's
--   end date has passed, the worker can be assigned to a new project.
--   Site engineers are exempt and may hold several ongoing projects.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assignment (
    assignment_id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
    worker_id        INT UNSIGNED NOT NULL,
    project_id       INT UNSIGNED NOT NULL,
    assignment_date  DATE         NOT NULL,
    PRIMARY KEY (assignment_id),
    UNIQUE KEY uq_worker_project (worker_id, project_id),   -- assigned once per project
    KEY idx_assignment_project (project_id),
    CONSTRAINT fk_assignment_worker
        FOREIGN KEY (worker_id)  REFERENCES worker (worker_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_assignment_project
        FOREIGN KEY (project_id) REFERENCES project (project_id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- TRIGGERS: one ongoing project per worker, except site engineers
-- (the Flask app installs these automatically on startup as well)
-- ---------------------------------------------------------------------
DELIMITER //

DROP TRIGGER IF EXISTS trg_assignment_single_project //
CREATE TRIGGER trg_assignment_single_project
BEFORE INSERT ON assignment
FOR EACH ROW
BEGIN
    DECLARE worker_role VARCHAR(50);
    DECLARE active_count INT;

    SELECT role INTO worker_role
    FROM worker WHERE worker_id = NEW.worker_id;
    SELECT COUNT(*) INTO active_count
    FROM assignment a
    JOIN project p ON p.project_id = a.project_id
    WHERE a.worker_id = NEW.worker_id
      AND (p.end_date IS NULL OR p.end_date >= CURDATE());

    IF active_count > 0
       AND LOCATE('engineer', LOWER(worker_role)) = 0
       AND LOCATE('engr', LOWER(worker_role)) = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Only site engineers can be assigned to more than one ongoing project.';
    END IF;
END //

DROP TRIGGER IF EXISTS trg_worker_single_project //
CREATE TRIGGER trg_worker_single_project
BEFORE UPDATE ON worker
FOR EACH ROW
BEGIN
    IF (LOCATE('engineer', LOWER(OLD.role)) > 0
        OR LOCATE('engr', LOWER(OLD.role)) > 0)
       AND LOCATE('engineer', LOWER(NEW.role)) = 0
       AND LOCATE('engr', LOWER(NEW.role)) = 0
       AND (SELECT COUNT(*)
            FROM assignment a
            JOIN project p ON p.project_id = a.project_id
            WHERE a.worker_id = NEW.worker_id
              AND (p.end_date IS NULL OR p.end_date >= CURDATE())) > 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'This worker has more than one ongoing project; only site engineers can hold multiple ongoing projects.';
    END IF;
END //

DELIMITER ;

-- ---------------------------------------------------------------------
-- ATTENDANCE (DTR): Assignment 1 : M Attendance
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance (
    attendance_id      INT UNSIGNED NOT NULL AUTO_INCREMENT,
    assignment_id      INT UNSIGNED NOT NULL,
    attendance_date    DATE         NOT NULL,
    time_in            TIME         NULL,
    time_out           TIME         NULL,
    attendance_status  ENUM('Present', 'Late', 'Absent', 'Half-day', 'On Leave')
                       NOT NULL DEFAULT 'Present',
    PRIMARY KEY (attendance_id),
    UNIQUE KEY uq_assignment_date (assignment_id, attendance_date),  -- one DTR entry per day
    KEY idx_attendance_date (attendance_date),
    CONSTRAINT fk_attendance_assignment
        FOREIGN KEY (assignment_id) REFERENCES assignment (assignment_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_time_order CHECK (time_out IS NULL OR time_in IS NULL OR time_out > time_in)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- PROJECT_FILE: supports "Store project files" (plans, contracts, reports)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project_file (
    file_id      INT UNSIGNED NOT NULL AUTO_INCREMENT,
    project_id   INT UNSIGNED NOT NULL,
    file_name    VARCHAR(255) NOT NULL,
    file_type    VARCHAR(20)  NULL,               -- e.g. pdf, dwg, xlsx
    description  VARCHAR(255) NULL,
    uploaded_on  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    file_data    LONGBLOB     NOT NULL,           -- up to 4 GB per file
    PRIMARY KEY (file_id),
    KEY idx_file_project (project_id),
    CONSTRAINT fk_file_project
        FOREIGN KEY (project_id) REFERENCES project (project_id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- VIEW: Daily Time Record with computed total hours
-- (Worker ID, Date, Time-in, Time-out, Status, Total Hours)
-- 1-hour lunch is deducted when the shift covers 12:00-13:00
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_dtr AS
SELECT
    w.worker_id,
    CONCAT(w.first_name, ' ', w.last_name)          AS worker_name,
    w.role,
    p.project_id,
    p.project_name,
    at.attendance_id,
    at.attendance_date,
    at.time_in,
    at.time_out,
    at.attendance_status,
    CASE
        WHEN at.time_in IS NULL OR at.time_out IS NULL THEN 0
        ELSE ROUND(
            TIME_TO_SEC(TIMEDIFF(at.time_out, at.time_in)) / 3600
            - IF(at.time_in < '12:00:00' AND at.time_out > '13:00:00', 1, 0),
        2)
    END                                             AS total_hours,
    w.worker_rate
FROM attendance  at
JOIN assignment  a ON a.assignment_id = at.assignment_id
JOIN worker      w ON w.worker_id     = a.worker_id
JOIN project     p ON p.project_id    = a.project_id;

-- ---------------------------------------------------------------------
-- VIEW: Payroll summary per worker per day-range (max 8 paid hrs/day)
-- Use: SELECT ... FROM v_dtr WHERE attendance_date BETWEEN ? AND ?
-- Example query (period Nov 9-13, 2026):
--
-- SELECT worker_id, worker_name, role, worker_rate,
--        SUM(attendance_status IN ('Present','Late','Half-day')) AS days_worked,
--        SUM(attendance_status = 'Absent')                       AS days_absent,
--        ROUND(SUM(total_hours), 2)                              AS actual_hours,
--        ROUND(SUM(LEAST(total_hours, 8)), 2)                    AS paid_hours,
--        ROUND(SUM(LEAST(total_hours, 8)) / 8 * worker_rate, 2)  AS gross_pay
-- FROM v_dtr
-- WHERE attendance_date BETWEEN '2026-11-09' AND '2026-11-13'
-- GROUP BY worker_id, worker_name, role, worker_rate
-- ORDER BY worker_name;
-- ---------------------------------------------------------------------
