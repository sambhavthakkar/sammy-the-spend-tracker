#!/usr/bin/env python3
"""
BudgetBot Main Entry Point
Choose between running CLI interface (for testing) or API server (for production)
"""
import sys
import os
import argparse

def run_cli():
    """Run the CLI interface for testing"""
    from src.cli_interface import BudgetBotCLI
    cli = BudgetBotCLI()
    cli.start()

def run_api():
    """Run the API server for production"""
    from src.api import create_app
    from src.config import Config

    app = create_app()

    # Get configuration from environment
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = Config.DEBUG

    print(f"🚀 Starting BudgetBot API server on {host}:{port}")
    print(f"📊 Environment: {os.getenv('FLASK_ENV', 'production')}")
    print(f"🔧 Debug mode: {debug}")

    app.run(host=host, port=port, debug=debug)

def main():
    """Main application entry point"""
    parser = argparse.ArgumentParser(description='BudgetBot - WhatsApp Native Financial OS')
    parser.add_argument(
        'mode',
        choices=['cli', 'api'],
        nargs='?',
        default='cli',
        help='Run mode: cli for testing interface, api for production server'
    )

    args = parser.parse_args()

    print("🤖 BudgetBot - WhatsApp Native Financial OS")
    print("=" * 50)

    if args.mode == 'cli':
        print("Starting CLI interface for testing...")
        run_cli()
    elif args.mode == 'api':
        print("Starting API server for production...")
        run_api()

if __name__ == "__main__":
    main()