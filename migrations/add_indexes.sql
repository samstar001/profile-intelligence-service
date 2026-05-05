-- Stage 4B: Database Indexes
-- Run once on production Neon database

CREATE INDEX IF NOT EXISTS idx_profiles_gender ON profiles (gender);
CREATE INDEX IF NOT EXISTS idx_profiles_country_id ON profiles (UPPER(country_id));
CREATE INDEX IF NOT EXISTS idx_profiles_age_group ON profiles (age_group);
CREATE INDEX IF NOT EXISTS idx_profiles_age ON profiles (age);
CREATE INDEX IF NOT EXISTS idx_profiles_created_at ON profiles (created_at);
CREATE INDEX IF NOT EXISTS idx_profiles_gender_probability ON profiles (gender_probability);
CREATE INDEX IF NOT EXISTS idx_profiles_gender_country_agegroup ON profiles (gender, country_id, age_group);
CREATE INDEX IF NOT EXISTS idx_profiles_gender_age ON profiles (gender, age);