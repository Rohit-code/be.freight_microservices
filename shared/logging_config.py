"""
Shared logging configuration for all microservices.
Provides clean, concise logging with essential information only.
"""
import logging
import sys
import warnings
from typing import Optional


def setup_service_logging(
    service_name: str,
    log_level: str = "INFO",
    suppress_warnings: bool = True,
    startup_message: Optional[str] = None
) -> logging.Logger:
    """
    Set up standardized logging for a microservice.
    
    Args:
        service_name: Name of the service (e.g., "email", "auth", "rate-sheet")
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        suppress_warnings: Whether to suppress non-essential warnings
        startup_message: Custom startup message (optional)
    
    Returns:
        Configured logger instance
    """
    # Suppress warnings if requested
    if suppress_warnings:
        # Suppress Pydantic v1 compatibility warnings
        warnings.filterwarnings("ignore", ".*Core Pydantic V1 functionality.*")
        
        # Suppress bcrypt version warnings (common with Python 3.14)
        warnings.filterwarnings("ignore", ".*error reading bcrypt version.*")
        
        # Suppress Python 3.14 multiprocessing warnings
        warnings.filterwarnings("ignore", ".*resource_tracker.*leaked semaphore objects.*")
        warnings.filterwarnings("ignore", ".*There appear to be.*leaked semaphore objects.*")
        
        # Suppress other common warnings
        warnings.filterwarnings("ignore", ".*watchfiles.*")
        warnings.filterwarnings("ignore", ".*reloader.*")
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True  # Override existing configuration
    )
    
    # Create service-specific logger
    logger = logging.getLogger(service_name)
    
    # Set noisy loggers to WARNING level to reduce noise
    noisy_loggers = [
        "uvicorn",
        "uvicorn.error", 
        "uvicorn.access",
        "watchfiles.main",
        "passlib.handlers.bcrypt",  # Suppress bcrypt version warnings
        "httpx",  # Reduce HTTP request logging noise
        "multiprocessing.resource_tracker",  # Suppress Python 3.14 semaphore warnings
    ]
    
    for noisy_logger in noisy_loggers:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    
    return logger


def log_service_startup(logger: logging.Logger, service_name: str, port: int, version: str = "1.0.0"):
    """Log essential startup information in a clean format"""
    logger.info(f"🚀 {service_name.title()} Service v{version} - Port {port}")


def log_service_ready(logger: logging.Logger, service_name: str, additional_info: Optional[str] = None):
    """Log service ready status"""
    base_message = f"✅ {service_name.title()} Service Ready"
    if additional_info:
        logger.info(f"{base_message} ({additional_info})")
    else:
        logger.info(base_message)


def log_dependency_status(logger: logging.Logger, service_name: str, status: str):
    """Log dependency status concisely"""
    status_emoji = "✅" if status == "ok" else "⚠️"
    logger.info(f"{status_emoji} {service_name}: {status}")


def log_service_shutdown(logger: logging.Logger, service_name: str):
    """Log service shutdown"""
    logger.info(f"🛑 {service_name.title()} Service Shutting Down")


class QuietStartupFilter(logging.Filter):
    """Filter to suppress noisy startup messages"""
    
    SUPPRESS_PATTERNS = [
        "Will watch for changes in these directories",
        "Started reloader process", 
        "Started server process",
        "Waiting for application startup",
        "Application startup complete",
        "Shared error handlers not available",
        "error reading bcrypt version",  # Suppress bcrypt warnings
        "HTTP Request:",  # Suppress HTTP request logs (can be re-enabled if needed)
        "leaked semaphore objects",  # Suppress Python 3.14 multiprocessing warnings
        "resource_tracker:",  # Suppress resource tracker warnings
    ]
    
    def filter(self, record):
        message = record.getMessage()
        return not any(pattern in message for pattern in self.SUPPRESS_PATTERNS)


def apply_quiet_filter():
    """Apply quiet filter to reduce startup noise"""
    quiet_filter = QuietStartupFilter()
    
    # Apply to common noisy loggers
    noisy_loggers = [
        "uvicorn",
        "uvicorn.error", 
        "watchfiles.main",
        "",  # Root logger
    ]
    
    for logger_name in noisy_loggers:
        logger = logging.getLogger(logger_name)
        logger.addFilter(quiet_filter)