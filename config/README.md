# Database Configuration

This directory contains database configuration files for the NGS Knowledge Base project.

## Configuration Files

- `db_local.json` - Local Homebrew PostgreSQL database (localhost:5432)
- `db_supabase.json` - Supabase local development database (127.0.0.1:54322)
- `db_config.py` - Utility module for loading configs and creating connections

## Usage

### In Python Scripts

```python
from config.db_config import get_connection

# Use default config (local)
conn = get_connection()

# Use specific config
conn = get_connection('supabase')

# Use environment variable
# export DB_CONFIG=supabase
conn = get_connection()
```

### Command Line Scripts

Most query scripts now support the `--db-config` parameter:

```bash
# Use local database (default)
python scripts/query/aspect_search.py "your query"

# Use Supabase database
python scripts/query/aspect_search.py "your query" --db-config supabase

# Set environment variable for all scripts
export DB_CONFIG=supabase
python scripts/query/aspect_search.py "your query"
```

### Web Applications

Streamlit apps (`web_query.py`, etc.) have a dropdown selector in the sidebar to choose between database configurations.

## Configuration Format

Each config file is a JSON file with the following structure:

```json
{
  "name": "config_name",
  "description": "Human-readable description",
  "host": "hostname or IP",
  "port": 5432,
  "database": "database_name",
  "user": "username",
  "password": "password"
}
```

## Available Configurations

### local
- **Host:** localhost
- **Port:** 5432
- **Database:** mngs_kb
- **User:** david
- **Description:** Local Homebrew PostgreSQL installation

### supabase
- **Host:** 127.0.0.1
- **Port:** 54322
- **Database:** postgres
- **User:** postgres
- **Description:** Supabase local development environment

## Viewing Configuration Details

```bash
# List all available configs
python config/db_config.py

# Show specific config details
python config/db_config.py local
python config/db_config.py supabase
```

## Updated Scripts

The following scripts have been updated to use the config system:

**Query Scripts:**
- `scripts/query/aspect_search.py`
- `scripts/query/web_aspect_search.py`
- `scripts/query/query_kb.py`
- `scripts/query/web_query.py` (Streamlit app)

All scripts default to using the `local` configuration for backward compatibility.

## Security Notes

⚠️ **Warning:** Config files contain database credentials in plain text. For production use:
- Never commit credentials to version control
- Use environment variables or secret management systems
- Restrict file permissions: `chmod 600 config/db_*.json`
- Consider using `.env` files with python-dotenv

## Environment Variable Override

You can set the `DB_CONFIG` environment variable to change the default configuration:

```bash
export DB_CONFIG=supabase
python scripts/query/query_kb.py -q "your query"
```

This is useful for CI/CD pipelines or when you want to switch configurations without modifying command-line arguments.
