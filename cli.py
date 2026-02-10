"""Command-line interface for Xray to Qase migration."""

import argparse
import json
import sys
from pathlib import Path

from orchestrator import MigrationOrchestrator
from utils.cache_manager import CacheManager
from utils.logger import setup_logger, get_logger


def load_config(config_path: str) -> dict:
    """
    Load configuration from JSON file.
    
    Args:
        config_path: Path to config file
    
    Returns:
        Configuration dictionary
    
    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config file is invalid JSON
    """
    config_file = Path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    return config


def cmd_extract(args):
    """Run extraction phase."""
    logger = get_logger(__name__)
    
    try:
        config = load_config(args.config)
        
        # Setup logging
        log_file = args.log_file or (Path("logs") / "extraction.log")
        setup_logger(log_file=str(log_file), level=args.log_level)
        
        # Create orchestrator
        orchestrator = MigrationOrchestrator(config)
        
        # Run extraction
        stats = orchestrator.extract()
        
        logger.info(f"Extraction completed. Cache directory: {orchestrator.cache_manager.cache_dir}")
        return 0
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}", exc_info=True)
        return 1


def cmd_transform(args):
    """Run transformation phase."""
    logger = get_logger(__name__)
    logger.error("Transform phase is NOT YET IMPLEMENTED. Only extract phase is available.")
    
    try:
        cache_dir = Path(args.cache)
        
        if not cache_dir.exists():
            raise ValueError(f"Cache directory does not exist: {cache_dir}")
        
        # Setup logging
        log_file = args.log_file or (cache_dir / "transform.log")
        setup_logger(log_file=str(log_file), level=args.log_level)
        
        # Load config from cache or use provided config
        if args.config:
            config = load_config(args.config)
        else:
            cache_manager = CacheManager(cache_dir)
            metadata = cache_manager.load_metadata()
            if not metadata:
                raise ValueError("No metadata found in cache. Please provide --config")
            config = {}  # Minimal config for transform
        
        # Create orchestrator with existing cache
        orchestrator = MigrationOrchestrator(config, cache_dir=cache_dir)
        
        # Run transformation
        stats = orchestrator.transform()
        
        logger.info("Transformation completed")
        return 0
        
    except Exception as e:
        logger.error(f"Transformation failed: {e}", exc_info=True)
        return 1


def cmd_load(args):
    """Run load phase."""
    logger = get_logger(__name__)
    logger.error("Load phase is NOT YET IMPLEMENTED. Only extract phase is available.")
    
    try:
        cache_dir = Path(args.cache)
        
        if not cache_dir.exists():
            raise ValueError(f"Cache directory does not exist: {cache_dir}")
        
        # Setup logging
        log_file = args.log_file or (cache_dir / "load.log")
        setup_logger(log_file=str(log_file), level=args.log_level)
        
        # Load config
        config = load_config(args.config)
        
        # Create orchestrator with existing cache
        orchestrator = MigrationOrchestrator(config, cache_dir=cache_dir)
        
        # Run load
        stats = orchestrator.load()
        
        logger.info("Load completed")
        return 0
        
    except Exception as e:
        logger.error(f"Load failed: {e}", exc_info=True)
        return 1


def cmd_migrate(args):
    """Run all phases in sequence."""
    logger = get_logger(__name__)
    logger.warning("Only EXTRACT phase is implemented. Transform and Load phases will be skipped.")
    
    try:
        config = load_config(args.config)
        
        # Setup logging
        log_file = args.log_file or (Path("logs") / "migration.log")
        setup_logger(log_file=str(log_file), level=args.log_level)
        
        # Create orchestrator
        orchestrator = MigrationOrchestrator(config)
        
        # Run full migration
        results = orchestrator.migrate()
        
        logger.info(f"Migration completed. Cache directory: {orchestrator.cache_manager.cache_dir}")
        return 0
        
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Xray Cloud to Qase Migration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract data from Xray Cloud (ONLY THIS IS IMPLEMENTED)
  python cli.py extract
  
  # Extract with custom config file
  python cli.py extract --config config.json
  
  # Transform cached data (NOT YET IMPLEMENTED)
  python cli.py transform --cache ./cache/xray_extraction_20260205_143022/
  
  # Load transformed data into Qase (NOT YET IMPLEMENTED)
  python cli.py load --cache ./cache/xray_extraction_20260205_143022/
  
  # Run all phases at once (ONLY EXTRACT WORKS)
  python cli.py migrate
        """
    )
    
    # Global arguments
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )
    parser.add_argument(
        "--log-file",
        help="Path to log file (default: logs/[phase].log or cache/[phase].log)"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Extract command
    extract_parser = subparsers.add_parser("extract", help="Extract data from Xray Cloud")
    extract_parser.add_argument(
        "--config",
        default="config.json",
        help="Path to configuration file (default: config.json)"
    )
    extract_parser.set_defaults(func=cmd_extract)
    
    # Transform command
    transform_parser = subparsers.add_parser("transform", help="Transform cached data to Qase format (NOT YET IMPLEMENTED)")
    transform_parser.add_argument(
        "--cache",
        required=True,
        help="Path to cache directory"
    )
    transform_parser.add_argument(
        "--config",
        default="config.json",
        help="Path to configuration file (default: config.json, optional for transform)"
    )
    transform_parser.set_defaults(func=cmd_transform)
    
    # Load command
    load_parser = subparsers.add_parser("load", help="Load transformed data into Qase (NOT YET IMPLEMENTED)")
    load_parser.add_argument(
        "--cache",
        required=True,
        help="Path to cache directory"
    )
    load_parser.add_argument(
        "--config",
        default="config.json",
        help="Path to configuration file (default: config.json)"
    )
    load_parser.set_defaults(func=cmd_load)
    
    # Migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Run all phases (extract, transform, load) - ONLY EXTRACT WORKS")
    migrate_parser.add_argument(
        "--config",
        default="config.json",
        help="Path to configuration file (default: config.json)"
    )
    migrate_parser.set_defaults(func=cmd_migrate)
    
    # Parse arguments and run command
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
