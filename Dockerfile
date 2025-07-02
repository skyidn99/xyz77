# Dockerfile (Final, Robust Version)

# Stage 1: Build the Go application
FROM golang:1.21-alpine AS builder
WORKDIR /app

# Copy ONLY the module definition file first
COPY go.mod ./

# Copy the application code that uses the modules
COPY main.go ./

# THIS IS THE KEY: go mod tidy reads main.go, sees the imports,
# and generates a perfect go.sum file with all dependencies.
RUN go mod tidy

# Now that dependencies are sorted, build the application.
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/bot .

# Stage 2: Create the final small image
FROM alpine:latest
WORKDIR /app
COPY --from=builder /app/bot /app/bot

# Add SSL certificates so our Go app can make HTTPS requests
RUN apk --no-cache add ca-certificates

# Run our bot
CMD ["/app/bot"]
