-- Users Table (Common for both job seekers and employers)
CREATE TABLE users (
    user_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    user_type VARCHAR(20) CHECK (user_type IN ('job_seeker', 'employer')) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Job Seekers Table
CREATE TABLE job_seekers (
    seeker_id INT REFERENCES users(user_id),
    resume JSON NOT NULL,  -- Storing resume in JSON format
    additional_info JSON,  -- Additional information in JSON format
    PRIMARY KEY (seeker_id)
);

-- Employers Table
CREATE TABLE employers (
    employer_id INT REFERENCES users(user_id),
    company_name VARCHAR(100),
    company_info JSON,  -- Company information in JSON format
    PRIMARY KEY (employer_id)
);

-- Job Listings Table
CREATE TABLE job_listings (
    job_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employer_id INT REFERENCES employers(employer_id),
    title VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    location VARCHAR(100),
    posted_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) CHECK (status IN ('open', 'closed')) DEFAULT 'open'
);

-- Applications Table
CREATE TABLE applications (
    application_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id INT REFERENCES job_listings(job_id),
    seeker_id INT REFERENCES job_seekers(seeker_id),
    application_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) CHECK (status IN ('pending', 'accepted', 'rejected')) DEFAULT 'pending'
);

-- Creating an index for faster searches on job listings
CREATE INDEX idx_job_listings ON job_listings(title, location);
