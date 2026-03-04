-- Optional: run this if routes table already exists without space_available/space_unit.
-- New deployments using create_all() will get these columns from the model.
-- If columns already exist, the ALTER will fail; that is fine.

ALTER TABLE routes ADD COLUMN space_available INTEGER;
ALTER TABLE routes ADD COLUMN space_unit VARCHAR(20);
