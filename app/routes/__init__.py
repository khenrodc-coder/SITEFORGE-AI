"""Route modules. Each module defines one Flask blueprint."""


def register_blueprints(app):
    from app.routes.api import api_bp
    from app.routes.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
