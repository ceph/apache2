/* Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "httpd.h"
#include "http_config.h"
#include "http_request.h"
#include "http_connection.h"
#include "http_protocol.h"
#include "http_log.h"
#include "util_filter.h"
#define APR_WANT_STRFUNC
#include "apr_strings.h"

module AP_MODULE_DECLARE_DATA reqtimeout_module;

typedef struct
{
    int header_timeout;     /* timeout for reading the req hdrs in secs */
    int header_max_timeout; /* max timeout for req hdrs in secs */
    int header_min_rate;    /* min rate for reading req hdrs in bytes/s */
    apr_time_t header_rate_factor;
    int body_timeout;       /* timeout for reading the req body in secs */
    int body_max_timeout;   /* max timeout for req body in secs */
    int body_min_rate;      /* timeout for reading the req body in secs */
    apr_time_t body_rate_factor;
} reqtimeout_srv_cfg;

typedef struct
{
    apr_time_t timeout_at;
    apr_time_t max_timeout_at;
    int min_rate;
    int new_timeout;
    int new_max_timeout;
    int in_keep_alive;
    char *type;
    apr_time_t rate_factor;
} reqtimeout_con_cfg;

typedef struct
{
    apr_socket_t *socket;
} reqtimeout_ctx;

static const char *const reqtimeout_filter_name = "reqtimeout";

static void extend_timeout(reqtimeout_con_cfg *ccfg, apr_bucket_brigade *bb)
{
    apr_off_t len;
    apr_time_t new_timeout_at;

    if (apr_brigade_length(bb, 0, &len) != APR_SUCCESS || len <= 0)
        return;

    new_timeout_at = ccfg->timeout_at + len * ccfg->rate_factor;
    if (ccfg->max_timeout_at > 0 && new_timeout_at > ccfg->max_timeout_at) {
        ccfg->timeout_at = ccfg->max_timeout_at;
    }
    else {
        ccfg->timeout_at = new_timeout_at;
    }
}

static apr_status_t reqtimeout_filter(ap_filter_t *f,
                                      apr_bucket_brigade *bb,
                                      ap_input_mode_t mode,
                                      apr_read_type_e block,
                                      apr_off_t readbytes)
{
    reqtimeout_ctx *ctx;
    apr_time_t time_left;
    apr_time_t now;
    apr_status_t rv;
    apr_interval_time_t saved_sock_timeout = -1;
    reqtimeout_con_cfg *ccfg;

    ctx = f->ctx;
    AP_DEBUG_ASSERT(ctx != NULL);

    ccfg = ap_get_module_config(f->c->conn_config, &reqtimeout_module);
    AP_DEBUG_ASSERT(ccfg != NULL);

    if (ccfg->in_keep_alive) {
        /* For this read, the normal keep-alive timeout must be used */
        ccfg->in_keep_alive = 0;
        return ap_get_brigade(f->next, bb, mode, block, readbytes);
    }

    now = apr_time_now();
    if (ccfg->new_timeout > 0) {
        /* set new timeout */
        ccfg->timeout_at = now + apr_time_from_sec(ccfg->new_timeout);
        ccfg->new_timeout = 0;
        if (ccfg->new_max_timeout > 0) {
            ccfg->max_timeout_at = now + apr_time_from_sec(ccfg->new_max_timeout);
            ccfg->new_max_timeout = 0;
        }
    }
    else if (ccfg->timeout_at == 0) {
        /* no timeout set */
        return ap_get_brigade(f->next, bb, mode, block, readbytes);
    }

    time_left = ccfg->timeout_at - now;
    if (time_left <= 0) {
        ap_log_cerror(APLOG_MARK, APLOG_INFO, 0, f->c,
                      "Request %s read timeout", ccfg->type);
        return APR_TIMEUP;
    }

    if (block == APR_NONBLOCK_READ || mode == AP_MODE_INIT
        || mode == AP_MODE_EATCRLF) {
        rv = ap_get_brigade(f->next, bb, mode, block, readbytes);
        if (ccfg->min_rate > 0 && rv == APR_SUCCESS) {
            extend_timeout(ccfg, bb);
        }
        return rv;
    }

    if (time_left < apr_time_from_sec(1)) {
        time_left = apr_time_from_sec(1);
    }

    rv = apr_socket_timeout_get(ctx->socket, &saved_sock_timeout);
    AP_DEBUG_ASSERT(rv == APR_SUCCESS);

    if (saved_sock_timeout >= time_left) {
        rv = apr_socket_timeout_set(ctx->socket, time_left);
        AP_DEBUG_ASSERT(rv == APR_SUCCESS);
    }
    else {
        saved_sock_timeout = -1;
    }

    rv = ap_get_brigade(f->next, bb, mode, block, readbytes);

    if (saved_sock_timeout != -1) {
        apr_socket_timeout_set(ctx->socket, saved_sock_timeout);
    }

    if (ccfg->min_rate > 0 && rv == APR_SUCCESS) {
        extend_timeout(ccfg, bb);
    }

    if (APR_STATUS_IS_TIMEUP(rv)) {
        ap_log_cerror(APLOG_MARK, APLOG_INFO, 0, f->c,
                      "Request %s read timeout", ccfg->type);
    }
    return rv;
}

static int reqtimeout_pre_conn(conn_rec *c, void *csd)
{
    reqtimeout_ctx *ctx;
    reqtimeout_con_cfg *ccfg;
    reqtimeout_srv_cfg *cfg;

    cfg = ap_get_module_config(c->base_server->module_config,
                               &reqtimeout_module);
    AP_DEBUG_ASSERT(cfg != NULL);
    if (cfg->header_timeout <= 0 && cfg->body_timeout <= 0) {
        /* not configured for this vhost */
        return OK;
    }

    ctx = apr_pcalloc(c->pool, sizeof(reqtimeout_ctx));
    ctx->socket = csd;

    ccfg = apr_pcalloc(c->pool, sizeof(reqtimeout_con_cfg));
    ccfg->new_timeout = cfg->header_timeout;
    ccfg->new_max_timeout = cfg->header_max_timeout;
    ccfg->type = "header";
    ccfg->min_rate = cfg->header_min_rate;
    ccfg->rate_factor = cfg->header_rate_factor;
    ap_set_module_config(c->conn_config, &reqtimeout_module, ccfg);

    ap_add_input_filter("reqtimeout", ctx, NULL, c);
    return OK;
}

static int reqtimeout_after_headers(request_rec *r)
{
    reqtimeout_srv_cfg *cfg;
    reqtimeout_con_cfg *ccfg =
        ap_get_module_config(r->connection->conn_config, &reqtimeout_module);

    if (ccfg == NULL) {
        /* not configured for this vhost */
        return OK;
    }

    cfg = ap_get_module_config(r->connection->base_server->module_config,
                               &reqtimeout_module);
    AP_DEBUG_ASSERT(cfg != NULL);

    ccfg->timeout_at = 0;
    ccfg->max_timeout_at = 0;
    ccfg->new_timeout = cfg->body_timeout;
    ccfg->new_max_timeout = cfg->body_max_timeout;
    ccfg->min_rate = cfg->body_min_rate;
    ccfg->rate_factor = cfg->body_rate_factor;
    ccfg->type = "body";

    return OK;
}

static int reqtimeout_after_body(request_rec *r)
{
    reqtimeout_srv_cfg *cfg;
    reqtimeout_con_cfg *ccfg =
        ap_get_module_config(r->connection->conn_config, &reqtimeout_module);

    if (ccfg == NULL) {
        /* not configured for this vhost */
        return OK;
    }

    cfg = ap_get_module_config(r->connection->base_server->module_config,
                               &reqtimeout_module);
    AP_DEBUG_ASSERT(cfg != NULL);

    ccfg->timeout_at = 0;
    ccfg->max_timeout_at = 0;
    ccfg->in_keep_alive = 1;
    ccfg->new_timeout = cfg->header_timeout;
    ccfg->new_max_timeout = cfg->header_max_timeout;
    ccfg->min_rate = cfg->header_min_rate;
    ccfg->rate_factor = cfg->header_rate_factor;
    
    ccfg->type = "header";

    return OK;
}

static void *reqtimeout_create_srv_config(apr_pool_t *p, server_rec *s)
{
    reqtimeout_srv_cfg *cfg = apr_pcalloc(p, sizeof(reqtimeout_srv_cfg));

    cfg->header_timeout = -1;
    cfg->header_max_timeout = -1;
    cfg->header_min_rate = -1;
    cfg->body_timeout = -1;
    cfg->body_max_timeout = -1;
    cfg->body_min_rate = -1;

    return cfg;
}

#define MERGE_INT(cfg, b, a, val) cfg->val = (a->val == -1) ? b->val : a->val;
static void *reqtimeout_merge_srv_config(apr_pool_t *p, void *base_, void *add_)
{
    reqtimeout_srv_cfg *base = base_;
    reqtimeout_srv_cfg *add  = add_;
    reqtimeout_srv_cfg *cfg  = apr_pcalloc(p, sizeof(reqtimeout_srv_cfg));

    MERGE_INT(cfg, base, add, header_timeout);
    MERGE_INT(cfg, base, add, header_max_timeout);
    MERGE_INT(cfg, base, add, header_min_rate);
    MERGE_INT(cfg, base, add, body_timeout);
    MERGE_INT(cfg, base, add, body_max_timeout);
    MERGE_INT(cfg, base, add, body_min_rate);

    cfg->header_rate_factor = (cfg->header_min_rate == -1) ? base->header_rate_factor :
                              add->header_rate_factor;
    cfg->body_rate_factor = (cfg->body_min_rate == -1) ? base->body_rate_factor :
    			     add->body_rate_factor;

    return cfg;
}

static const char *parse_int(apr_pool_t *p, const char *arg, int *val) {
    char *endptr;
    *val = strtol(arg, &endptr, 10);

    if (arg == endptr) {
        return apr_psprintf(p, "Value '%s' not numerical", endptr);
    }
    if (*endptr != '\0') {
        return apr_psprintf(p, "Cannot parse '%s'", endptr);
    }
    if (*val < 0) {
        return "Value must be non-negative";
    }
    return NULL;
}

static const char *set_reqtimeout_param(reqtimeout_srv_cfg *conf,
                                      apr_pool_t *p,
                                      const char *key,
                                      const char *val)
{
    const char *ret = NULL;
    char *rate_str = NULL, *initial_str, *max_str = NULL;
    int rate = 0, initial = 0, max = 0;
    enum { PARAM_HEADER, PARAM_BODY } type;

    if (!strcasecmp(key, "header")) {
        type = PARAM_HEADER;
    }
    else if (!strcasecmp(key, "body")) {
        type = PARAM_BODY;
    }
    else {
        return "Unknown RequestReadTimeout parameter";
    }
    
    if ((rate_str = ap_strcasestr(val, ",minrate="))) {
        initial_str = apr_pstrndup(p, val, rate_str - val);
        rate_str += strlen(",minrate=");
        ret = parse_int(p, rate_str, &rate);
        if (ret)
            return ret;

        if (rate == 0)
            return "Minimum data rate must be larger than 0";

        if ((max_str = strchr(initial_str, '-'))) {
            *max_str++ = '\0';
            ret = parse_int(p, max_str, &max);
            if (ret)
                return ret;
        }
        
        ret = parse_int(p, initial_str, &initial);
    }
    else {
        if (ap_strchr_c(val, '-'))
            return "Must set MinRate option if using timeout range";
        ret = parse_int(p, val, &initial);
    }
        
    if (ret)
        return ret;

    if (max && initial >= max) {
        return "Maximum timeout must be larger than initial timeout";
    }

    if (type == PARAM_HEADER) {
        conf->header_timeout = initial;
        conf->header_max_timeout = max;
        conf->header_min_rate = rate;
        if (rate)
            conf->header_rate_factor = apr_time_from_sec(1) / rate;
    }
    else {
        conf->body_timeout = initial;
        conf->body_max_timeout = max;
        conf->body_min_rate = rate;
        if (rate)
            conf->body_rate_factor = apr_time_from_sec(1) / rate;
    }
    return ret;
}

static const char *set_reqtimeouts(cmd_parms *cmd, void *mconfig,
                                   const char *arg)
{
    reqtimeout_srv_cfg *conf =
    ap_get_module_config(cmd->server->module_config,
                         &reqtimeout_module);
    
    while (*arg) {
        char *word, *val;
        const char *err;
        
        word = ap_getword_conf(cmd->pool, &arg);
        val = strchr(word, '=');
        if (!val) {
            return "Invalid RequestReadTimeout parameter. Parameter must be "
            "in the form 'key=value'";
        }
        else
            *val++ = '\0';

        err = set_reqtimeout_param(conf, cmd->pool, word, val);
        
        if (err)
            return apr_psprintf(cmd->temp_pool, "RequestReadTimeout: %s=%s: %s",
                               word, val, err);
    }
    
    return NULL;
    
}

static void reqtimeout_hooks(apr_pool_t *pool)
{
    /*
     * mod_ssl is AP_FTYPE_CONNECTION + 5 and mod_reqtimeout needs to
     * be called before mod_ssl. Otherwise repeated reads during the ssl
     * handshake can prevent the timeout from triggering.
     */
    ap_register_input_filter(reqtimeout_filter_name, reqtimeout_filter, NULL,
                             AP_FTYPE_CONNECTION + 8);
    ap_hook_pre_connection(reqtimeout_pre_conn, NULL, NULL, APR_HOOK_MIDDLE);
    ap_hook_post_read_request(reqtimeout_after_headers, NULL, NULL,
                              APR_HOOK_MIDDLE);
    ap_hook_log_transaction(reqtimeout_after_body, NULL, NULL,
                            APR_HOOK_MIDDLE);
}

static const command_rec reqtimeout_cmds[] = {
    AP_INIT_RAW_ARGS("RequestReadTimeout", set_reqtimeouts, NULL, RSRC_CONF,
                     "Set various timeout parameters for reading request "
                     "headers and body"),
    {NULL}
};

module AP_MODULE_DECLARE_DATA reqtimeout_module = {
    STANDARD20_MODULE_STUFF,
    NULL,                           /* create per-dir config structures */
    NULL,                           /* merge  per-dir config structures */
    reqtimeout_create_srv_config,   /* create per-server config structures */
    reqtimeout_merge_srv_config,    /* merge per-server config structures */
    reqtimeout_cmds,                /* table of config file commands */
    reqtimeout_hooks
};
