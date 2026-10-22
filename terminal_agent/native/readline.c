#define _XOPEN_SOURCE 700
#define _DEFAULT_SOURCE
#include <readline/readline.h>
#include <readline/keymaps.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <limits.h>
#include <wchar.h>
#include <errno.h>
#include <dlfcn.h>
#include <fcntl.h>

/* Bash loadable-builtin ABI. We use only the stable word/builtin descriptors,
 * so building does not require a separate bash-devel package. All Readline
 * functions resolve to the host Bash, never a second libreadline instance. */
typedef struct word_desc { char *word; int flags; } WORD_DESC;
typedef struct word_list { struct word_list *next; WORD_DESC *word; } WORD_LIST;
struct builtin {
    char *name; int (*function)(WORD_LIST *); int flags;
    char * const *long_doc; const char *short_doc; char *handle;
};
extern char *get_string_value(const char *);
static char *root;
static char session[PATH_MAX - 64];
static rl_command_func_t *old_tab;
static int old_tab_type;
static char *old_tab_macro;
static int *last_column, *last_row, *visible_bottom, *display_fixed;
static rl_voidfunc_t *original_redisplay;
static char *passive_body, *passive_buttons;
static int passive_visible, passive_row, overlay_active;
static rl_command_func_t *old_enter[2];
static int old_enter_type[2];
static char *old_enter_macro[2];
static volatile sig_atomic_t resized;
static int cosmos_ui;
static int widget(int, int);


static const char *variable(const char *name, const char *fallback) {
    const char *value = get_string_value(name);
    return value && *value ? value : fallback;
}
static void on_resize(int unused) { (void)unused; resized = 1; }
static int characters(const char *text, int bytes) {
    int count = 0;
    for (int i = 0; text[i] && i < bytes; i++)
        if (((unsigned char)text[i] & 0xc0) != 0x80) count++;
    return count;
}
static int bytes_for_characters(const char *text, int count) {
    int i = 0, seen = 0;
    while (text[i]) {
        if (((unsigned char)text[i] & 0xc0) != 0x80 && seen++ == count) break;
        i++;
    }
    return i;
}
static void geometry(const char *text, int width, int *row, int *column) {
    mbstate_t state = {0};
    int hidden = 0;
    while (*text) {
        unsigned char ch = *text;
        if (ch == 1) { hidden = 1; text++; continue; }
        if (ch == 2) { hidden = 0; text++; continue; }
        if (hidden) { text++; continue; }
        if (ch == 27) {
            text++;
            if (*text == '[') {
                text++;
                while (*text && !(*text >= '@' && *text <= '~')) text++;
                if (*text) text++;
            } else if (*text == ']') {
                text++;
                while (*text && *text != 7 && !(*text == 27 && text[1] == '\\')) text++;
                if (*text == 7) text++;
                else if (*text) text += 2;
            } else if (*text) text++;
            continue;
        }
        if (ch == '\n') { (*row)++; *column = 0; text++; continue; }
        if (ch == '\r') { *column = 0; text++; continue; }
        wchar_t wc;
        size_t n = mbrtowc(&wc, text, strlen(text), &state);
        if (n == (size_t)-1 || n == (size_t)-2) { n = 1; memset(&state, 0, sizeof state); wc = '?'; }
        if (!n) break;
        int cells = ch == '\t' ? 8 - *column % 8 : wcwidth(wc);
        if (cells < 0) cells = 2; /* Readline renders control characters as ^X. */
        if (*column + cells > width) { (*row)++; *column = 0; }
        *column += cells;
        if (*column >= width) { (*row)++; *column = 0; }
        text += n;
    }
}
static void move_rows(int delta) {
    if (delta > 0) fprintf(rl_outstream, "\033[%dB", delta);
    if (delta < 0) fprintf(rl_outstream, "\033[%dA", -delta);
}
static void clear_passive(void) {
    if (!passive_visible) return;
    int delta = passive_row - *last_row;
    fputc('\r', rl_outstream);
    move_rows(delta);
    fputs("\033[2K", rl_outstream);
    move_rows(-delta);
    if (*last_column) fprintf(rl_outstream, "\033[%dC", *last_column);
    fflush(rl_outstream);
    passive_visible = 0;
}
/* Only SGR escapes from the Python snapshot are replayed: no cursor movement
 * or autowrap changes can escape the single-row native rendering contract. */
static int clipped_span(const char *text, int budget) {
    mbstate_t state = {0};
    int cells = 0, clipped = 0;
    while (*text) {
        if (*text == 27) {
            const char *start = text++;
            if (*text == '[') {
                text++;
                while (*text && !(*text >= '@' && *text <= '~')) text++;
                if (*text == 'm') fwrite(start, 1, (size_t)(text - start + 1), rl_outstream);
                if (*text) text++;
            } else if (*text) text++;
            continue;
        }
        wchar_t wc;
        size_t n = mbrtowc(&wc, text, strlen(text), &state);
        if (n == (size_t)-1 || n == (size_t)-2) { n = 1; memset(&state, 0, sizeof state); wc = '?'; }
        if (!n) break;
        int width = wcwidth(wc);
        if (width < 0) { text += n; continue; }
        if (cells + width > budget) clipped = 1;
        if (!clipped) { fwrite(text, 1, n, rl_outstream); cells += width; }
        text += n;
    }
    return cells;
}
static void paint_passive(void) {
    if (!passive_body || !*passive_body) return;
    struct winsize size = {0};
    ioctl(fileno(rl_outstream), TIOCGWINSZ, &size);
    int width = size.ws_col ? size.ws_col : 80;
    int bottom = *visible_bottom > *last_row ? *visible_bottom : *last_row;
    fputc('\r', rl_outstream);
    move_rows(bottom - *last_row);
    /* A newline reserves room even at the screen bottom. Restore relatively
     * afterwards so scrolling does not invalidate a saved absolute cursor. */
    fputs("\n\033[2K\033[?7l", rl_outstream);
    int total = width > 1 ? width - 1 : 0;
    int body_width = total > 9 ? total - 9 : 0;
    int painted = clipped_span(passive_body, body_width);
    while (painted++ < body_width) fputc(' ', rl_outstream);
    fputs("\033[0m", rl_outstream);
    clipped_span(passive_buttons ? passive_buttons : "", total - body_width);
    fputs("\033[0m\033[?7h\r", rl_outstream);
    passive_row = bottom + 1;
    move_rows(*last_row - passive_row);
    if (*last_column) fprintf(rl_outstream, "\033[%dC", *last_column);
    fflush(rl_outstream);
    passive_visible = 1;
}
static void redisplay_with_passive(void) {
    /* While the child owns the tty, prep/resize may request a native redraw.
     * The widget performs one explicit redraw after re-anchoring the cursor. */
    if (overlay_active) return;
    clear_passive();
    original_redisplay();
    paint_passive();
}
static void finish(void);
static int accept_native(int count, int key) {
    (void)count;
    clear_passive();
    finish();
    /* Dispatch through the user's restored Enter binding, rather than eval. */
    rl_stuff_char(key);
    return 0;
}
static void finish(void) {
    if (*session) {
        if (original_redisplay) rl_redisplay_function = original_redisplay;
        original_redisplay = NULL;
        free(passive_body); passive_body = NULL;
        free(passive_buttons); passive_buttons = NULL;
        passive_visible = overlay_active = 0;
        for (int i = 0; i < 2; i++) {
            const char *binding = i ? "\n" : "\r";
            if (old_enter_type[i] == ISMACR)
                rl_generic_bind(ISMACR, binding, old_enter_macro[i], rl_get_keymap());
            else if (old_enter[i]) rl_bind_keyseq(binding, old_enter[i]);
            else rl_unbind_key_in_map(i ? '\n' : '\r', rl_get_keymap());
            free(old_enter_macro[i]); old_enter_macro[i] = NULL;
        }
        const char *names[] = {"line", "line.point", "line.action", "line.bar", "line.buttons", "state.json", NULL};
        char path[PATH_MAX];
        for (int i = 0; names[i]; i++) {
            snprintf(path, sizeof path, "%s/%s", session, names[i]);
            unlink(path);
        }
        rmdir(session);
        *session = 0;
        if (old_tab_type == ISMACR)
            rl_generic_bind(ISMACR, "\t", old_tab_macro, rl_get_keymap());
        else if (old_tab)
            rl_bind_keyseq("\t", old_tab);
        else
            rl_unbind_key_in_map('\t', rl_get_keymap());
        free(old_tab_macro); old_tab_macro = NULL;
    }
}
static int create_session(void) {
    if (*session) return 0;
    const char *runtime = variable("XDG_RUNTIME_DIR", "");
    char directory[PATH_MAX - 128];
    if (*runtime) {
        if (snprintf(directory, sizeof directory, "%s/terminal-agent", runtime) >= (int)sizeof directory) return -1;
    } else {
        snprintf(directory, sizeof directory, "/tmp/terminal-agent-%lu", (unsigned long)getuid());
    }
    if (mkdir(directory, 0700) && errno != EEXIST) return -1;
    struct stat info;
    if (lstat(directory, &info) || !S_ISDIR(info.st_mode) || info.st_uid != getuid() || (info.st_mode & 0077)) {
        fputs("terminal-agent: unsafe runtime directory ownership or permissions\n", stderr);
        return -1;
    }
    snprintf(session, sizeof session, "%s/session-XXXXXX", directory);
    if (!mkdtemp(session)) { *session = 0; return -1; }
    old_tab = rl_function_of_keyseq("\t", rl_get_keymap(), &old_tab_type);
    if (old_tab_type == ISMACR) old_tab_macro = strdup((char *)old_tab);
    rl_bind_keyseq("\t", widget);
    for (int i = 0; i < 2; i++) {
        const char *binding = i ? "\n" : "\r";
        old_enter[i] = rl_function_of_keyseq(binding, rl_get_keymap(), &old_enter_type[i]);
        if (old_enter_type[i] == ISMACR) old_enter_macro[i] = strdup((char *)old_enter[i]);
        rl_bind_keyseq(binding, accept_native);
    }
    original_redisplay = rl_redisplay_function;
    rl_redisplay_function = redisplay_with_passive;
    return 0;
}
static char *read_file(const char *suffix) {
    char path[PATH_MAX];
    snprintf(path, sizeof path, "%s/%s", session, suffix);
    FILE *fp = fopen(path, "rb");
    if (!fp) return NULL;
    if (fseek(fp, 0, SEEK_END)) { fclose(fp); return NULL; }
    long size = ftell(fp);
    if (size < 0 || size > 1024 * 1024) { fclose(fp); return NULL; }
    rewind(fp);
    char *text = malloc(size + 1);
    if (!text) { fclose(fp); return NULL; }
    size_t got = fread(text, 1, size, fp);
    text[got] = 0;
    fclose(fp);
    return text;
}
/* Discover a live Cosmos endpoint without a shell command or inherited flag:
 * existing Bash panes can acquire a presenter after their startup. */
static int cosmos_available(void) {
    const char *tmux = variable("TMUX", ""), *pane = variable("TMUX_PANE", "");
    if (!*tmux || !*pane) return 0;
    char *socket_path = strdup(tmux);
    if (!socket_path) return 0;
    char *comma = strchr(socket_path, ',');
    if (comma) *comma = 0;
    int channel[2];
    if (pipe(channel)) { free(socket_path); return 0; }
    pid_t child = fork();
    if (!child) {
        close(channel[0]);
        dup2(channel[1], STDOUT_FILENO);
        close(channel[1]);
        int null = open("/dev/null", O_RDWR);
        if (null >= 0) { dup2(null, STDIN_FILENO); dup2(null, STDERR_FILENO); close(null); }
        execlp("tmux", "tmux", "-S", socket_path, "show-options", "-pqv", "-t", pane, "@cosmos_agent_socket", (char *)NULL);
        _exit(127);
    }
    free(socket_path);
    close(channel[1]);
    char address[PATH_MAX];
    ssize_t count = 0, got;
    while (count < (ssize_t)sizeof(address) - 1) {
        got = read(channel[0], address + count, sizeof(address) - 1 - count);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) break;
        count += got;
    }
    close(channel[0]);
    if (child < 0) return 0;
    int status = 0;
    pid_t waited;
    do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
    /* Bash may reap the query child in its SIGCHLD handler. The fully read
     * response and same-UID socket validation remain authoritative. */
    if (waited < 0 && errno != ECHILD) return 0;
    if (waited > 0 && (!WIFEXITED(status) || WEXITSTATUS(status))) return 0;
    while (count && (address[count - 1] == '\n' || address[count - 1] == '\r')) count--;
    address[count] = 0;
    struct stat info;
    return count && !lstat(address, &info) && S_ISSOCK(info.st_mode) && info.st_uid == getuid();
}

static int helper(int cursor) {
    char output[PATH_MAX], state[PATH_MAX], point[32];
    snprintf(output, sizeof output, "%s/line", session);
    snprintf(state, sizeof state, "%s/state.json", session);
    snprintf(point, sizeof point, "%d", characters(rl_line_buffer, cursor));
    const char *python = variable("TERMINAL_AGENT_PYTHON", "python3");
    int demo = !strcmp(variable("TERMINAL_AGENT_DEMO", "0"), "1");
    char stale[PATH_MAX];
    const char *outputs[] = {"line", "line.point", "line.action"};
    for (int i = 0; i < 3; i++) {
        snprintf(stale, sizeof stale, "%s/%s", session, outputs[i]);
        unlink(stale);
    }
    pid_t child = fork();
    if (child < 0) return -1;
    if (!child) {
        const char *old_path = getenv("PYTHONPATH");
        size_t size = strlen(root) + (old_path ? strlen(old_path) : 0) + 2;
        char *path = malloc(size);
        if (!path) _exit(127);
        snprintf(path, size, "%s%s%s", root, old_path ? ":" : "", old_path ? old_path : "");
        setenv("PYTHONPATH", path, 1);
        char source[192] = "{}";
        if (cosmos_ui) {
            setenv("TERMINAL_AGENT_COSMOS_UI", "1", 1);
            struct winsize size = {0};
            ioctl(fileno(rl_outstream), TIOCGWINSZ, &size);
            int prefix_rows = 0, column = 0;
            const char *prompt = rl_prompt ? rl_prompt : "";
            const char *last = strrchr(prompt, '\n');
            if (last) {
                char *prefix = strndup(prompt, last - prompt + 1);
                if (prefix) { geometry(prefix, size.ws_col ? size.ws_col : 80, &prefix_rows, &column); free(prefix); }
            }
            snprintf(source, sizeof source, "{\"columns\":%d,\"rows\":%d,\"before\":%d,\"after\":%d}",
                size.ws_col, size.ws_row, *last_row + prefix_rows,
                *visible_bottom > *last_row ? *visible_bottom - *last_row : 0);
            setenv("TERMINAL_AGENT_SOURCE_RECT", source, 1);
        } else {
            unsetenv("TERMINAL_AGENT_COSMOS_UI");
            unsetenv("TERMINAL_AGENT_SOURCE_RECT");
        }
        const char *args[24] = {python, "-m", "terminal_agent.cli", "--shell", "--readline",
            "--output", output, "--state", state, "--shell-line", rl_line_buffer,
            "--shell-point", point, NULL};
        int argc = 13;
        if (demo) args[argc++] = "--demo";
        if (cosmos_ui) {
            args[argc++] = "--cosmos-ui";
            args[argc++] = "--source-geometry";
            args[argc++] = source;
        }
        args[argc] = NULL;
        execvp(python, (char * const *)args);
        _exit(127);
    }
    int status;
    while (waitpid(child, &status, 0) < 0) {
        if (errno == EINTR) continue;
        if (errno == ECHILD) return 0;
        return -1;
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}
/* Cosmos owns the overlay. Keep Readline's tty and display cache intact:
 * no popup row reservation, mode cycling, manual cursor movement, or PS1 replay. */
static int cosmos_widget(void) {
    int saved_point = rl_point;
    for (;;) {
        struct sigaction previous, handler = {0};
        struct winsize before = {0}, after = {0};
        handler.sa_handler = on_resize;
        sigemptyset(&handler.sa_mask);
        resized = 0;
        ioctl(fileno(rl_outstream), TIOCGWINSZ, &before);
        sigaction(SIGWINCH, &handler, &previous);
        int status = helper(saved_point);
        ioctl(fileno(rl_outstream), TIOCGWINSZ, &after);
        sigaction(SIGWINCH, &previous, NULL);
        char *line = status == 0 ? read_file("line") : NULL;
        char *action = status == 0 ? read_file("line.action") : NULL;
        char *point = status == 0 ? read_file("line.point") : NULL;
        if (!line || !action) {
            free(line); free(action); free(point);
            finish();
            return 1;
        }
        int update = !strcmp(action, "update");
        int relocate = !strcmp(action, "relocate");
        int edit = !strcmp(action, "edit"), run = !strcmp(action, "run");
        int changed = strcmp(line, rl_line_buffer), old_point = rl_point;
        if (changed) rl_replace_line(line, 0);
        rl_point = update ? rl_end : saved_point;
        if (point && !update) rl_point = bytes_for_characters(line, atoi(point));
        if (rl_point > rl_end) rl_point = rl_end;
        saved_point = rl_point;
        free(line); free(action); free(point);
        if (before.ws_col != after.ws_col)
            rl_resize_terminal();
        else if (before.ws_row != after.ws_row)
            rl_set_screen_size(after.ws_row, after.ws_col);
        if (changed || old_point != rl_point || resized) rl_redisplay();
        if (update || relocate) continue;
        if (edit) {
            overlay_active = 0;
            rl_redisplay_function = redisplay_with_passive;
            *display_fixed = 1;
            return 0;
        }
        finish();
        *display_fixed = 1;
        if (run) rl_done = 1;
        return 0;
    }
}

static int widget(int count, int key) {
    (void)count; (void)key;
    cosmos_ui = cosmos_available();
    if (create_session()) return 1;
    overlay_active = 1;
    rl_redisplay_function = original_redisplay;
    clear_passive();
    free(passive_body); passive_body = NULL;
    free(passive_buttons); passive_buttons = NULL;
    if (cosmos_ui) return cosmos_widget();
    int saved_point = rl_point;
    for (;;) {
        /* Moving the existing cursor is enough: no prompt output, no erase. */
        rl_point = rl_end;
        rl_redisplay();
        int column = *last_column;
        int saved_display_row = *last_row;
        struct winsize before = {0}, after = {0};
        ioctl(fileno(rl_outstream), TIOCGWINSZ, &before);
        struct sigaction previous, handler = {0};
        handler.sa_handler = on_resize;
        sigemptyset(&handler.sa_mask);
        resized = 0;
        sigaction(SIGWINCH, &handler, &previous);
        rl_deprep_terminal();
        fputs("\r\n", rl_outstream);
        fflush(rl_outstream);
        int status = helper(saved_point);
        ioctl(fileno(rl_outstream), TIOCGWINSZ, &after);
        /* The child erases only its popup and leaves its cursor at that origin.
         * Relative movement also works when reserving the row scrolled the tty. */
        int changed_size = resized || before.ws_col != after.ws_col || before.ws_row != after.ws_row;
        int row = 0;
        if (changed_size) {
            column = 0;
            const char *prompt = rl_display_prompt ? rl_display_prompt : rl_prompt;
            const char *last = strrchr(prompt, '\n');
            geometry(last ? last + 1 : prompt, after.ws_col ? after.ws_col : 80, &row, &column);
            geometry(rl_line_buffer, after.ws_col ? after.ws_col : 80, &row, &column);
        }
        fprintf(rl_outstream, "\r\033[1A");
        if (column) fprintf(rl_outstream, "\033[%dC", column);
        fflush(rl_outstream);
        rl_prep_terminal(1);
        if (!changed_size) {
            /* Terminal-mode cycling resets Readline's cursor accounting to zero,
             * but the terminal cursor has already been restored to the old end.
             * Keep the cached coordinates in sync before the next diff render. */
            *last_column = column;
            *last_row = saved_display_row;
        }
        sigaction(SIGWINCH, &previous, NULL);
        if (changed_size) {
            /* Terminal reflow invalidates Readline's old-width screen cache.
             * Re-anchor at the command origin and ask the native renderer to
             * recompute wraps. Only resize needs a complete layout refresh. */
            fprintf(rl_outstream, "\r");
            if (row) fprintf(rl_outstream, "\033[%dA", row);
            fflush(rl_outstream);
            rl_on_new_line();
            rl_resize_terminal();
        }
        char *line = status == 0 ? read_file("line") : NULL;
        char *action = status == 0 ? read_file("line.action") : NULL;
        char *point = status == 0 ? read_file("line.point") : NULL;
        if (line && action) {
            int is_update = !strcmp(action, "update");
            rl_replace_line(line, 0);
            rl_point = is_update ? rl_end : saved_point;
            if (point && !is_update) rl_point = bytes_for_characters(line, atoi(point));
            if (rl_point > rl_end) rl_point = rl_end;
            saved_point = rl_point;
            rl_redisplay(); /* Readline diffs its own screen cache. */
            int edit = !strcmp(action, "edit"), run = !strcmp(action, "run");
            free(line); free(point); free(action);
            if (is_update) continue;
            if (edit) {
                passive_body = read_file("line.bar");
                passive_buttons = read_file("line.buttons");
                overlay_active = 0;
                rl_redisplay_function = redisplay_with_passive;
                paint_passive();
                return 0;
            }
            finish();
            if (run) rl_done = 1; /* Native accept-line; normal history/execution. */
            return 0;
        }
        free(line); free(point); free(action);
        rl_point = saved_point;
        rl_redisplay();
        finish();
        return 1;
    }
}
static int builtin(WORD_LIST *args) {
    const char *operation = args ? args->word->word : "";
    if (!strcmp(operation, "reset")) { finish(); return 0; }
    if (!strcmp(operation, "install") && args->next) {
        last_column = dlsym(RTLD_DEFAULT, "_rl_last_c_pos");
        last_row = dlsym(RTLD_DEFAULT, "_rl_last_v_pos");
        visible_bottom = dlsym(RTLD_DEFAULT, "_rl_vis_botlin");
        display_fixed = dlsym(RTLD_DEFAULT, "rl_display_fixed");
        if (!last_column || !last_row || !visible_bottom || !display_fixed) {
            fputs("terminal-agent: this Bash does not export compatible Readline cursor state\n", stderr);
            return 1;
        }
        finish();
        free(root); root = strdup(args->next->word->word);
        return rl_bind_keyseq("\030\001", widget);
    }
    fputs("usage: terminal_agent_native install ROOT | reset\n", stderr);
    return 2;
}
static char *docs[] = {"Native Readline adapter for the one-row terminal-agent popup.", NULL};
struct builtin terminal_agent_native_struct = {
    "terminal_agent_native", builtin, 1, docs,
    "terminal_agent_native install ROOT | reset", NULL
};
