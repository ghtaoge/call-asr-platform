FROM golang:1.23 AS build
WORKDIR /src
COPY go.mod ./
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/siprec-gateway ./cmd/gateway

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/siprec-gateway /siprec-gateway
USER nonroot:nonroot
EXPOSE 5061/tcp 5061/udp 8081/tcp
ENTRYPOINT ["/siprec-gateway"]
