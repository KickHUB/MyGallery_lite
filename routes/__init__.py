from .gallery import bp as gallery_bp
from .trash import bp as trash_bp
from .failed import bp as failed_bp
from .quarantine import bp as quarantine_bp
from .stats import bp as stats_bp
from .booru import bp as booru_bp
from .server_settings import bp as server_settings_bp
from .repo_update import bp as repo_update_bp

def register_all(app):
    for bp in (
        gallery_bp,
        trash_bp,
        failed_bp,
        quarantine_bp,
        stats_bp,
        booru_bp,
        server_settings_bp,
        repo_update_bp,
    ):
        app.register_blueprint(bp)
