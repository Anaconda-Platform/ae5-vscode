ARG WORKSPACE
FROM $WORKSPACE
COPY . /aesrc/vscode/
RUN set -ex \
    && rm -f /usr/bin/git /usr/bin/git-* \
    && for fname in /opt/continuum/anaconda/envs/lab_launch/bin/{git,git-*}; do \
           ln -s $fname /usr/bin/; \
       done \
    ##
    && cd /aesrc/vscode \
    ##
    ## Download code-server and extensions
    && /opt/continuum/anaconda/envs/lab_launch/bin/python download.py \
    ##
    ## install code-server
    && tar xfz downloads/code-server.tar.gz \
    && chown -fR anaconda:anaconda code-server-* \
    && mv code-server-* /opt/continuum/anaconda/envs/lab_launch/lib/code-server \
    && ln -s "/opt/continuum/anaconda/envs/lab_launch/lib/code-server/code-server" \
          /opt/continuum/anaconda/envs/lab_launch/bin \
    ##
    ## Move in the user-data-dir
    && mv vscode /opt/continuum/.vscode \
    && chown -fR anaconda:anaconda /opt/continuum/.vscode \
    ##
    ## install extensions
    && for ext in downloads/extensions/*.vsix; do \
        su anaconda -c \
          "/opt/continuum/anaconda/envs/lab_launch/bin/code-server \
          --user-data-dir /opt/continuum/.vscode \
          --install-extension $ext"; \
       done \
    ##
    ## extension post-install
    && /opt/continuum/anaconda/envs/lab_launch/bin/python download.py --post-install \
    ##
    ## Choose the right startup script
    && if [ ! -f /opt/continuum/scripts/start_user.sh ]; then \
           cp start_*.sh startup.sh build_condarc.py run_tool.py /opt/continuum/scripts; \
       else \
           cp start_vscode.sh /opt/continuum/scripts; \
       fi \
    ##
    && cp merge_vscode_settings.py /opt/continuum/scripts \
    && cp post-commit pre-push pre-push.py retag.py /opt/continuum/scripts \
    ##
    && chmod +x /opt/continuum/scripts/*.sh \
    && chown -R anaconda:anaconda /opt/continuum/scripts/* \
    ##
    ## Cleanup
    && rm -rf /aesrc/vscode/downloads \
    && rm -f /aesrc/vscode/{"*.tar.bz2", "*.tar.gz", "*.visx"}
