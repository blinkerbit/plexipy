# MCP (Model Context Protocol) Configuration

This project includes MCP server configuration for use with Cursor/antigravity IDE.

## Configuration Files

- **`.cursor/mcp.json`** - MCP server configuration
- **`.cursor/settings.json`** - Cursor IDE settings with MCP integration

## MCP Servers Configured

### 1. SonarQube (this project)
- **Purpose**: Code quality and security analysis via SonarQube MCP Server
- **Command**: `docker run -i --rm ... mcp/sonarqube`
- **Environment**: `SONARQUBE_TOKEN` (user token), `SONARQUBE_URL` (server URL), `SONARQUBE_IDE_PORT` (e.g. 64120 for SonarLint/Cursor)
- **Setup**: Edit `.cursor/mcp.json` and set your user token and IDE port. Use a **user token** (not project/global token).
  - **SonarQube Server**: set `SONARQUBE_URL` (e.g. `https://your-sonarqube.example.com`).
  - **SonarQube Cloud**: replace `SONARQUBE_URL` with `SONARQUBE_ORG` in both `args` and `env` (e.g. `"SONARQUBE_ORG": "your-org"`).
- **Docs**: [SonarQube MCP Server](https://docs.sonarsource.com/sonarqube-mcp-server), [Using with Cursor](https://docs.sonarsource.com/sonarqube-mcp-server/using)

### 2. Antigravity AI
- **Purpose**: AI-powered code assistance
- **Command**: `npx -y @antigravity-ai/cli`
- **Environment**: Requires `ANTIGRAVITY_API_KEY`

### 3. Filesystem Server
- **Purpose**: File system operations
- **Command**: `npx -y @modelcontextprotocol/server-filesystem`
- **Scope**: `/app` directory

### 4. Web Server
- **Purpose**: Web content fetching
- **Command**: `npx -y @modelcontextprotocol/server-web`

### 5. Git Server
- **Purpose**: Git repository operations
- **Command**: `npx -y @modelcontextprotocol/server-git`
- **Scope**: Current repository

## Setup Instructions

### Option 1: Use Project-Level Configuration

The `.cursor/` directory contains project-specific MCP configuration. Cursor will automatically detect and use these settings when you open this project.

### Option 2: Import to Global Cursor Settings

**Windows:**
```
%APPDATA%\Cursor\User\settings.json
```

**macOS:**
```
~/Library/Application Support/Cursor/User/settings.json
```

**Linux:**
```
~/.config/Cursor/User/settings.json
```

Copy the MCP server configuration from `.cursor/settings.json` to your global settings file.

### Option 3: Use Cursor Settings UI

1. Open Cursor
2. Go to Settings (Ctrl+, or Cmd+,)
3. Search for "MCP" or "Model Context Protocol"
4. Add the server configurations manually

## Environment Variables

Set the following environment variables for MCP servers:

```bash
# Antigravity AI API Key
export ANTIGRAVITY_API_KEY="your-api-key-here"
```

Or create a `.env` file in the project root:

```env
ANTIGRAVITY_API_KEY=your-api-key-here
```

## Verifying MCP Setup

1. Open Cursor in this project
2. Check the MCP status in the status bar (bottom right)
3. You should see connected MCP servers listed
4. Try using MCP commands in the chat/command palette

## Troubleshooting

### MCP Servers Not Connecting

1. **Check Node.js**: Ensure Node.js is installed (`node --version`)
2. **Check npx**: Ensure npx is available (`npx --version`)
3. **Check API Keys**: Verify environment variables are set
4. **Check Logs**: View Cursor's output panel for MCP errors

### Permission Issues

If you see permission errors:
- Ensure the `.cursor/` directory has proper read permissions
- Check that npm/npx can execute without sudo/admin rights

### Network Issues

If MCP servers can't download packages:
- Check your internet connection
- Verify npm registry access: `npm config get registry`
- For air-gapped environments, configure npm proxy settings

## Customizing MCP Configuration

Edit `.cursor/mcp.json` or `.cursor/settings.json` to:
- Add additional MCP servers
- Modify server arguments
- Change environment variables
- Adjust server timeouts

## Additional Resources

- [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
- [Cursor MCP Guide](https://cursor.sh/docs/mcp)
- [Antigravity AI Documentation](https://antigravity.ai/docs)
