-- Runs once, on first container init, alongside the default POSTGRES_DB.
-- Keeps integration tests fully isolated from the local dev database.
CREATE DATABASE safehaven_test;
