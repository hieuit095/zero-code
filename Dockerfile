# ─── Stage 1: Build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (better layer caching)
COPY package.json package-lock.json* pnpm-lock.yaml* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install

# Copy source and build
COPY . .
RUN npm run build

# ─── Stage 2: Serve with Nginx ───────────────────────────────────────────────
FROM nginx:1.27-alpine AS production

# Copy built static files
COPY --from=build /app/dist /usr/share/nginx/html

# Custom nginx config for SPA routing
RUN cat > /etc/nginx/conf.d/default.conf << 'EOF'
server {
listen 80;
server_name _;
root /usr/share/nginx/html;
index index.html;

# SPA fallback: serve index.html for all routes
location / {
try_files $uri $uri/ /index.html;
}

# Proxy API requests to the backend
location /api/ {
proxy_pass http://orchestrator-api:8000;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
}

# Proxy WebSocket connections
location /ws/ {
proxy_pass http://orchestrator-api:8000;
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_set_header Host $host;
proxy_read_timeout 86400;
}

# Block direct access to internal MCP endpoints (Rule 3)
location /internal/ {
return 403;
}

# Security headers
add_header X-Frame-Options DENY;
add_header X-Content-Type-Options nosniff;
add_header X-XSS-Protection "1; mode=block";
}
EOF

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
