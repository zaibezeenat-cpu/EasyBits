class AppError(Exception):
    """Base exception for all application errors."""
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)

class DatabaseError(AppError):
    """Raised when a database operation fails."""
    def __init__(self, message: str):
        super().__init__(message, code="DATABASE_ERROR")

class AgentPipelineError(AppError):
    """Raised when the LangGraph pipeline fails."""
    def __init__(self, message: str):
        super().__init__(message, code="AGENT_PIPELINE_ERROR")

class ValidationError(AppError):
    """Raised when data validation fails."""
    def __init__(self, message: str):
        super().__init__(message, code="VALIDATION_ERROR")

class ScrapingError(AppError):
    """Raised when extraction/scraping fails."""
    def __init__(self, message: str):
        super().__init__(message, code="SCRAPING_ERROR")
