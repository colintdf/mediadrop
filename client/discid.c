#include <stdio.h>
#include <discid/discid.h>
int main(int argc, char **argv) {
    DiscId *disc = discid_new();
    if (!disc) return 1;
    if (!discid_read_sparse(disc, argc > 1 ? argv[1] : NULL, 0)) {
        fprintf(stderr, "%s\n", discid_get_error_msg(disc));
        discid_free(disc); return 1;
    }
    printf("%s\n", discid_get_id(disc));
    discid_free(disc); return 0;
}
