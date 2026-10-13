FROM nginx:1.27-alpine

# Copy nginx reverse proxy configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy static frontend assets
COPY index.html /usr/share/nginx/html/
COPY style.css /usr/share/nginx/html/
COPY app.js /usr/share/nginx/html/

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
