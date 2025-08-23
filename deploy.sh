
#!/bin/bash

# Pull latest changes from Git
echo "Pulling latest code from Git..."
git pull origin main

# Install/update dependencies using Pipenv
echo "Installing/updating dependencies..."
pipenv install --deploy --ignore-pipfile

# Generate migration (without a message)
echo "Generating migration..."
pipenv run flask db migrate --autogenerate

# Run database migrations
echo "Running migrations..."
pipenv run flask db upgrade

# Restart the systemd service
echo "Restarting triple-back service..."
sudo systemctl restart triple-back

echo "Deployment complete!"
sudo systemctl restart triple-back

echo "Deployment complete!"
