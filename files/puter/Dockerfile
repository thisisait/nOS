FROM ghcr.io/heyputer/puter:latest

# Fix CORS credentials (Puter 2.5.x bug — commented out in source)
RUN sed -i "s|// res.setHeader('Access-Control-Allow-Credentials', true);|res.setHeader('Access-Control-Allow-Credentials', true);|g" \
    /opt/puter/app/src/backend/src/modules/web/WebServerService.js

# Fix Socket.IO CORS credentials
RUN sed -i "s|cors: {|cors: { credentials: true,|g" \
    /opt/puter/app/src/backend/src/modules/web/SocketioService.js
