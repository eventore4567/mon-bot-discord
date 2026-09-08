-- Keep legacy/test user inserts compatible while local production auth writes auth_subject explicitly.
-- PostgreSQL unique indexes allow multiple NULLs, so local:* subjects remain uniquely constrained.
ALTER TABLE users ALTER COLUMN auth_subject DROP NOT NULL;
