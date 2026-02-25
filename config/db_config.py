"""Database configuration and connection utilities.

This module provides a centralized way to manage database connections
across all scripts. It supports multiple database configurations (local, supabase)
and allows switching between them via environment variable or function parameter.

Usage:
    # Use default configuration (local)
    from config.db_config import get_connection
    conn = get_connection()

    # Use specific configuration
    conn = get_connection('supabase')

    # Use environment variable
    export DB_CONFIG=supabase
    conn = get_connection()

    # Get connection parameters without connecting
    from config.db_config import get_config
    params = get_config('local')
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional
import psycopg2


# Default configuration name
DEFAULT_CONFIG = 'local'

# Config directory
CONFIG_DIR = Path(__file__).parent


def get_config(config_name: Optional[str] = None) -> Dict[str, str]:
    """Load database configuration from JSON file.

    Args:
        config_name: Name of the config file (without .json extension).
                    If None, uses DB_CONFIG env var or defaults to 'local'.

    Returns:
        Dictionary with database connection parameters.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        json.JSONDecodeError: If config file is invalid JSON.
    """
    if config_name is None:
        config_name = os.environ.get('DB_CONFIG', DEFAULT_CONFIG)

    config_file = CONFIG_DIR / f"db_{config_name}.json"

    if not config_file.exists():
        raise FileNotFoundError(
            f"Database config file not found: {config_file}\n"
            f"Available configs: {list_configs()}"
        )

    with open(config_file, 'r') as f:
        config = json.load(f)

    return config


def list_configs() -> list:
    """List available database configurations.

    Returns:
        List of config names (without db_ prefix and .json suffix).
    """
    configs = []
    for file in CONFIG_DIR.glob("db_*.json"):
        config_name = file.stem.replace('db_', '')
        configs.append(config_name)
    return sorted(configs)


def get_connection(config_name: Optional[str] = None, **kwargs) -> psycopg2.extensions.connection:
    """Get a database connection using the specified configuration.

    Args:
        config_name: Name of the config to use (without .json extension).
                    If None, uses DB_CONFIG env var or defaults to 'local'.
        **kwargs: Additional connection parameters to override config values.

    Returns:
        psycopg2 database connection.

    Example:
        # Use default config
        conn = get_connection()

        # Use supabase config
        conn = get_connection('supabase')

        # Override specific parameter
        conn = get_connection('local', database='other_db')
    """
    config = get_config(config_name)

    # Extract connection parameters (skip non-connection fields)
    conn_params = {
        'host': config.get('host'),
        'port': config.get('port'),
        'database': config.get('database'),
        'user': config.get('user'),
        'password': config.get('password'),
    }

    # Remove None values
    conn_params = {k: v for k, v in conn_params.items() if v is not None}

    # Override with any provided kwargs
    conn_params.update(kwargs)

    return psycopg2.connect(**conn_params)


def get_connection_string(config_name: Optional[str] = None) -> str:
    """Get a connection string for the specified configuration.

    Args:
        config_name: Name of the config to use.

    Returns:
        PostgreSQL connection string (URI format).

    Example:
        postgresql://user:password@host:port/database
    """
    config = get_config(config_name)

    user = config.get('user', '')
    password = config.get('password', '')
    host = config.get('host', 'localhost')
    port = config.get('port', 5432)
    database = config.get('database', '')

    # Build connection string
    if password:
        auth = f"{user}:{password}"
    elif user:
        auth = user
    else:
        auth = ""

    if auth:
        return f"postgresql://{auth}@{host}:{port}/{database}"
    else:
        return f"postgresql://{host}:{port}/{database}"


def print_config_info(config_name: Optional[str] = None):
    """Print information about a database configuration.

    Args:
        config_name: Name of the config to display. If None, shows all configs.
    """
    if config_name is None:
        print("Available database configurations:")
        print()
        for name in list_configs():
            print(f"  {name}:")
            config = get_config(name)
            print(f"    Description: {config.get('description', 'N/A')}")
            print(f"    Host:        {config.get('host', 'N/A')}")
            print(f"    Port:        {config.get('port', 'N/A')}")
            print(f"    Database:    {config.get('database', 'N/A')}")
            print(f"    User:        {config.get('user', 'N/A')}")
            print()
    else:
        config = get_config(config_name)
        print(f"Configuration: {config_name}")
        print(f"  Description: {config.get('description', 'N/A')}")
        print(f"  Host:        {config.get('host', 'N/A')}")
        print(f"  Port:        {config.get('port', 'N/A')}")
        print(f"  Database:    {config.get('database', 'N/A')}")
        print(f"  User:        {config.get('user', 'N/A')}")
        print()
        print(f"Connection string:")
        print(f"  {get_connection_string(config_name)}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        print_config_info(sys.argv[1])
    else:
        print_config_info()
