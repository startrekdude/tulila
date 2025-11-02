"""Make Tulila challenges accessible over a network, score submissions, and collect the results.

This package implements Tulila Server, the "official" user/admin interface to the core
Tulila module. It provides a web service that enables challenge recipients to submit
their solutions to challenges and commands that allow challenge administrators to
create new users and export scores.

This package is subdivided into many modules, which are documented in their own files.
As a general philisophy, modules are designed to provide services to other modules
while encapsulating as much complexity and providing as simple of an API as possible.

Two modules of special note are:
  1. _main, which provides the three entry points to Tulila Server. These are:
    - start, invoked (indirectly) by the service manager to start Tulila Server.
    - export_scores, invoked by an administrative tool that...you guessed it...
      exports scores.
    - create_users, invoked by an administrative tool that creates users.
  2. _routes, which implements the HTTP routes that challenge recipients use to
     interact with Tulila Server. In implementing these routes, it consumes
     many services provided by the other modules.

Functionality intended for use by challenge recipients is exposed over HTTP.
functionality intended for use by challenge administrators is exposed as command-line
programs; thus, challenge administrators must have shell access (and be members of
the tulila-admins group, though that's more the installer's concern).

The server component accepts a socket from systemd to listen on - if you want to change
the interface or port, you must do it there. Similarly, all configuration parameters
are passed in as environment variables set in systemd config files.
"""

from ._main import create_users, export_scores, start


__all__ = (
	"create_users",
	"export_scores",
	"start",
)
