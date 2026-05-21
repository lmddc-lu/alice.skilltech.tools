FROM node:lts-alpine as build

# Set working directory
WORKDIR /app

# Copy package.json and package-lock.json
COPY package*.json ./

# Install dependencies
RUN npm install
RUN npm install -g @angular/cli

# Copy the rest of the application
COPY . .

# Build the application with localization
RUN ng build --configuration=production

# Stage 2: Serve with NGINX
FROM nginx:alpine

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist/frontend/ /usr/share/nginx/html/

# Expose port 80
EXPOSE 80

# Start NGINX
CMD ["nginx", "-g", "daemon off;"]