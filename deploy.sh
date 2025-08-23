#!/bin/bash

# Set Flask environment
export FLASK_APP=app.py
export FLASK_ENV=production

# Pull latest code
echo "Pulling latest code from Git..."
git pull origin main

# Install/update dependencies
echo "Installing/updating dependencies..."
pipenv install --deploy --ignore-pipfile

# Generate migrations
echo "Generating migration..."
pipenv run flask db migrate -m "Auto migration"

# Apply migrations
echo "Running migrations..."
pipenv run flask db upgrade

# Restart service
echo "Restarting triple-back service..."
sudo systemctl restart triple-back

echo "Deployment complete!"
