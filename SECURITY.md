# Security Policy

## Supported Versions

We release security patches for the following versions of webscout-mcp:

| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | :white_check_mark: |
| 0.4.x   | :white_check_mark: |
| < 0.4   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in webscout-mcp, please report it to us privately. **Do not** create a public GitHub issue for security vulnerabilities.

### How to Report

1. **Email**: Send a detailed report to [wxs-lang@github.com]
2. **GitHub Security Advisory**: You can also report via GitHub's built-in security advisory system at https://github.com/wxs-lang/webscout-mcp/security/advisories/new

### What to Include

Please include as much information as possible:

- **Type of vulnerability**: (e.g., buffer overflow, SQL injection, XSS, SSRF, etc.)
- **Affected versions**: Which versions are affected?
- **Steps to reproduce**: Clear, step-by-step instructions to reproduce the vulnerability
- **Proof of concept**: Code snippets, screenshots, or logs demonstrating the issue
- **Impact assessment**: What could an attacker do with this vulnerability?
- **Suggested fix**: If you have a suggested patch or mitigation, please include it

### What to Expect

1. **Acknowledgment**: We will acknowledge your report within **48 hours**
2. **Initial assessment**: We will provide an initial assessment within **5 business days**
3. **Fix timeline**: We will work to release a fix as quickly as possible, typically within **2-4 weeks** depending on severity
4. **Credit**: We will credit you in the release notes and security advisory (unless you prefer to remain anonymous)

## Security Best Practices for Users

### General Security

- **Keep webscout-mcp updated**: Always use the latest supported version
- **Review dependencies**: Regularly check for vulnerable dependencies using `pip-audit`
- **Use virtual environments**: Install webscout-mcp in an isolated virtual environment

### SSRF Protection

webscout-mcp includes built-in SSRF (Server-Side Request Forgery) protection:

```python
from webscout_mcp.security import SSRFProtector

protector = SSRFProtector()
is_safe, reason = protector.validate_url("https://example.com")
```

By default, the following are blocked:
- Private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Localhost (127.0.0.0/8, ::1)
- Link-local addresses (169.254.0.0/16)
- Sensitive ports (22, 3306, 5432, 6379, etc.)
- Non-HTTP/HTTPS schemes (file://, ftp://, gopher://, etc.)

### Sensitive Data Protection

- **Never hardcode API keys**: Use environment variables or configuration files
- **Use .env files**: Store secrets in `.env` files (never commit them to version control)
- **Output filtering**: webscout-mcp includes output filtering to redact sensitive information

```python
from webscout_mcp.security import SecurityManager

security = SecurityManager()
filtered = security.filter_output("api_key=secret123 and password=hidden456")
# Result: "api_key=******** and password=********"
```

### Rate Limiting

webscout-mcp includes built-in rate limiting to prevent abuse:

```python
from webscout_mcp.rate_limiter import RateLimiter

limiter = RateLimiter(max_requests=10, per_seconds=60)
```

## Security-Related Features

webscout-mcp includes several security features out of the box:

- **SSRF Protection**: Blocks requests to internal networks and sensitive resources
- **Output Filtering**: Redacts API keys, passwords, and other sensitive data
- **Rate Limiting**: Prevents abuse and protects target websites
- **Robots.txt Compliance**: Respects website crawling policies
- **User-Agent Rotation**: Prevents fingerprinting (with realistic browser headers)
- **Security Headers**: Includes security headers in all requests
- **Cookie Management**: Secure cookie handling and persistence

## Dependency Security

We regularly audit our dependencies for vulnerabilities:

- **Dependabot**: Automated dependency updates and security alerts
- **Bandit**: Static security analysis in CI/CD
- **CodeQL**: Advanced code security scanning
- **pip-audit**: Regular dependency vulnerability scanning

## Acknowledgments

We thank the following for their contributions to webscout-mcp's security:

- Security researchers who responsibly disclose vulnerabilities
- The open-source community for their feedback and contributions
- Automated security tools that help us maintain high security standards

---

**Last updated**: August 2026

**Security contact**: [wxs-lang@github.com]
