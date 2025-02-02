/* SPDX-License-Identifier: LGPL-3.0-or-later */
/* Copyright (C) 2020 Intel Labs */

#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <stdarg.h>
#include "secret_prov.h"
#include "cross_comm.h"

#define SEND_STRING "MORE"


int test_secret_prov_connect() {
    int ret;

    struct ra_tls_ctx ctx = {0};

    bool is_constructor = false;
    char* str = getenv(SECRET_PROVISION_CONSTRUCTOR);
    if (str && (!strcmp(str, "1") || !strcmp(str, "true") || !strcmp(str, "TRUE")))
        is_constructor = true;

    if (!is_constructor) {
        /* secret provisioning was not run as part of initialization, run it now */
        ret = secret_provision_start("VM-0-3-ubuntu:4433",
                                     "certs/ca_cert.crt", &ctx);
        if (ret < 0) {
            log_error("[error] secret_provision_start() returned %d\n", ret);
            goto out;
        }
    }

    ret = 0;
out:
    secret_provision_destroy();
    secret_provision_close(&ctx);
    return ret;
}

static int list_dir(char *path) {
    DIR *d;
    struct dirent *dir;
	printf("------list_dir IN------\n");
	log_error("------list_dir IN: %s------\n", path);
    d = opendir(path);
    if (d) {
        while ((dir = readdir(d)) != NULL) {
			log_error("%s\n", dir->d_name);
        	printf("%s\n", dir->d_name);
        }
    }
    closedir(d);
	printf("------list_dir OUT------\n");
	log_error("------list_dir OUT------\n");
	return 0;
}

int secret_prov_test() {
    int ret;
    int bytes;

    struct ra_tls_ctx ctx = {0};

    uint8_t* secret1   = NULL;
    size_t secret1_size = 0;

    uint8_t secret2[3] = {0}; /* we expect second secret to be 2-char string */

    bool is_constructor = false;
    char* str = getenv(SECRET_PROVISION_CONSTRUCTOR);
    if (str && (!strcmp(str, "1") || !strcmp(str, "true") || !strcmp(str, "TRUE")))
        is_constructor = true;

    list_dir(".");
    list_dir("./certs");

    if (!is_constructor) {
        /* secret provisioning was not run as part of initialization, run it now */
        ret = secret_provision_start("VM-0-12-ubuntu:4433",
                                     "certs/ca_cert.crt", &ctx);
        if (ret < 0) {
            log_error("[error] secret_provision_start() returned %d\n", ret);
            goto out;
        }
    }

    ret = secret_provision_get(&secret1, &secret1_size);
    if (ret < 0) {
        log_error("[error] secret_provision_get() returned %d\n", ret);
        goto out;
    }
    if (!secret1_size) {
        log_error("[error] secret_provision_get() returned secret with size 0\n");
        goto out;
    }

    secret1[secret1_size - 1] = '\0';

    if (!is_constructor) {
        /* let's ask for another secret (just to show communication with secret-prov server) */
        bytes = secret_provision_write(&ctx, (uint8_t*)SEND_STRING, sizeof(SEND_STRING));
        if (bytes < 0) {
            log_error("[error] secret_provision_write() returned %d\n", bytes);
            goto out;
        }

        /* the secret we expect in return is a 2-char string */
        bytes = secret_provision_read(&ctx, secret2, sizeof(secret2));
        if (bytes < 0) {
            log_error("[error] secret_provision_read() returned %d\n", bytes);
            goto out;
        }
        if (bytes != sizeof(secret2)) {
            log_error("[error] secret_provision_read() returned secret with size %d"
                    " (expected %lu)\n", bytes, sizeof(secret2));
            goto out;
        }

        secret2[bytes - 1] = '\0';
    }

    printf("--- Received secret1 = '%s', secret2 = '%s' ---\n", secret1, secret2);
    ret = 0;
out:
    secret_provision_destroy();
    secret_provision_close(&ctx);
    return ret;
}
