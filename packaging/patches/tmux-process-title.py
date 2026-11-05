"""Linux tmux's PR_SET_NAME title is limited to 15 bytes; keep full ps args too.

Only rewrite the original argv span after copying arguments. Environment strings
remain untouched. This is a build-only patch for the pinned upstream revision.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1])
main = root / 'tmux.c'
source = main.read_text()
needle = '\tif (setlocale(LC_CTYPE, "en_US.UTF-8") == NULL &&'
if source.count(needle) != 1:
    raise SystemExit('Pinned tmux main changed; process-title patch needs review')
source = source.replace(needle, '''#if defined(__linux__) && !defined(HAVE_SETPROCTITLE)
\textern void cosmos_proctitle_init(int, char **);
\tcosmos_proctitle_init(argc, argv);
#endif

''' + needle)
main.write_text(source)
compat = root / 'compat/setproctitle.c'
source = compat.read_text().replace('#include <stdarg.h>', '#include <stdarg.h>\n#include <errno.h>')
source = source.replace('void\nsetproctitle(const char *fmt, ...)', '''static char *cosmos_title_start;
static size_t cosmos_title_size;
static const char *cosmos_program;

void
cosmos_proctitle_init(int argc, char **argv)
{
\tchar *end, *copy;
\tint i;

\tcosmos_program = strdup(getprogname());
\tif (cosmos_program == NULL)
\t\tabort();
\tcosmos_title_start = argv[0];
\tend = argv[0] + strlen(argv[0]) + 1;
\tfor (i = 1; i < argc && argv[i] == end; i++)
\t\tend = argv[i] + strlen(argv[i]) + 1;
\tcosmos_title_size = end - cosmos_title_start;
\tfor (i = 0; i < argc; i++) {
\t\tcopy = strdup(argv[i]);
\t\tif (copy == NULL)
\t\t\tabort();
\t\targv[i] = copy;
\t}
#if defined(HAVE_PROGRAM_INVOCATION_SHORT_NAME)
\tprogram_invocation_short_name = (char *)cosmos_program;
#endif
}

void
setproctitle(const char *fmt, ...)''')
source = source.replace('char\ttitle[16], name[16], *cp;', 'char\ttitle[256], name[512], *cp;')
source = source.replace('getprogname(), title', 'cosmos_program ? cosmos_program : getprogname(), title')
source = source.replace('\tprctl(PR_SET_NAME, name);', '''\t/* Linux comm has 15 usable bytes. Keep the executable identity there,
\t * and the complete role/socket in the ps argument title. */
\tprctl(PR_SET_NAME, cosmos_program ? cosmos_program : getprogname());
\tif (cosmos_title_start != NULL && cosmos_title_size > 0) {
\t\tmemset(cosmos_title_start, 0, cosmos_title_size);
\t\tsnprintf(cosmos_title_start, cosmos_title_size, "%s", name);
\t}''')
compat.write_text(source)
