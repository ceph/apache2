%define contentdir /var/www
%define suexec_caller apache
%define mmn 20051115
%define mpms worker event

Summary: Apache HTTP Server
Name: httpd
Version: 2.2.16
Release: 1
URL: http://httpd.apache.org/
Vendor: Apache Software Foundation
Source0: http://www.apache.org/dist/httpd/httpd-%{version}.tar.gz
License: Apache License, Version 2.0
Group: System Environment/Daemons
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root
BuildPrereq: apr-devel, apr-util-devel, openldap-devel, db4-devel, expat-devel, findutils, perl, pkgconfig, pcre-devel >= 5.0
BuildPrereq: /usr/bin/apr-1-config, /usr/bin/apu-1-config
Requires: apr >= 1.2.0, apr-util >= 1.2.0, pcre >= 5.0, gawk, /usr/share/magic.mime, /usr/bin/find, openldap
Prereq: /sbin/chkconfig, /bin/mktemp, /bin/rm, /bin/mv
Prereq: sh-utils, textutils, /usr/sbin/useradd
Provides: webserver
Provides: httpd-mmn = %{mmn}
Conflicts: thttpd
Obsoletes: apache, secureweb, mod_dav

%description
Apache is a powerful, full-featured, efficient, and freely-available
Web server. Apache is also the most popular Web server on the
Internet.

%package devel
Group: Development/Libraries
Summary: Development tools for the Apache HTTP server.
Obsoletes: secureweb-devel, apache-devel
Requires: libtool, httpd = %{version}
Requires: apr-devel >= 1.2.0, apr-util-devel >= 1.2.0

%description devel
The httpd-devel package contains the APXS binary and other files
that you need to build Dynamic Shared Objects (DSOs) for Apache.

If you are installing the Apache HTTP server and you want to be
able to compile or develop additional modules for Apache, you need
to install this package.

%package manual
Group: Documentation
Summary: Documentation for the Apache HTTP server.
Obsoletes: secureweb-manual, apache-manual

%description manual
The httpd-manual package contains the complete manual and
reference guide for the Apache HTTP server. The information can
also be found at http://httpd.apache.org/docs/.

%package -n mod_ssl
Group: System Environment/Daemons
Summary: SSL/TLS module for the Apache HTTP server
BuildPrereq: openssl-devel
Prereq: openssl, dev, /bin/cat
Requires: httpd, make, httpd-mmn = %{mmn}

%description -n mod_ssl
The mod_ssl module provides strong cryptography for the Apache Web
server via the Secure Sockets Layer (SSL) and Transport Layer
Security (TLS) protocols.

%prep
%setup -q

# Safety check: prevent build if defined MMN does not equal upstream MMN.
vmmn=`echo MODULE_MAGIC_NUMBER_MAJOR | cpp -include include/ap_mmn.h | sed -n '
/^2/p'`
if test "x${vmmn}" != "x%{mmn}"; then
   : Error: Upstream MMN is now ${vmmn}, packaged MMN is %{mmn}.
   : Update the mmn macro and rebuild.
   exit 1
fi

%build
# forcibly prevent use of bundled apr, apr-util, pcre
rm -rf srclib/{apr,apr-util,pcre}

# Before configure; fix location of build dir in generated apxs
%{__perl} -pi -e "s:\@exp_installbuilddir\@:%{_libdir}/httpd/build:g" \
	support/apxs.in

function mpmbuild()
{
mpm=$1; shift
mkdir $mpm; pushd $mpm
../configure \
 	--prefix=%{_sysconfdir}/httpd \
        --with-apr=/usr/bin/apr-1-config \
        --with-apr-util=/usr/bin/apu-1-config \
        --with-pcre=/usr/bin/pcre-config \
        --exec-prefix=%{_prefix} \
 	--bindir=%{_bindir} \
 	--sbindir=%{_sbindir} \
 	--mandir=%{_mandir} \
	--libdir=%{_libdir} \
	--sysconfdir=%{_sysconfdir}/httpd/conf \
	--includedir=%{_includedir}/httpd \
	--libexecdir=%{_libdir}/httpd/modules \
	--datadir=%{contentdir} \
        --with-installbuilddir=%{_libdir}/httpd/build \
	--with-mpm=$mpm \
	--enable-suexec --with-suexec \
	--with-suexec-caller=%{suexec_caller} \
	--with-suexec-docroot=%{contentdir} \
	--with-suexec-logfile=%{_localstatedir}/log/httpd/suexec.log \
	--with-suexec-bin=%{_sbindir}/suexec \
	--with-suexec-uidmin=500 --with-suexec-gidmin=500 \
	--enable-pie \
	--with-pcre \
	$*

make %{?_smp_mflags}
popd
}

 # Build everything and the kitchen sink with the prefork build
mpmbuild prefork \
        --enable-mods-shared=all \
        --enable-ssl --with-ssl --enable-distcache \
        --enable-proxy \
        --enable-cache \
        --enable-disk-cache \
        --enable-ldap --enable-authnz-ldap \
        --enable-cgid \
        --enable-authn-anon --enable-authn-alias \
        --disable-imagemap

# For the other MPMs, just build httpd and no optional modules
for f in %{mpms}; do
   mpmbuild $f --enable-mods-shared=all
done

%install
rm -rf $RPM_BUILD_ROOT

pushd prefork
make DESTDIR=$RPM_BUILD_ROOT install
popd

# install alternative MPMs
for f in %{mpms}; do
  install -m 755 ${f}/httpd $RPM_BUILD_ROOT%{_sbindir}/httpd.${f}
done

# for holding mod_dav lock database
mkdir -p $RPM_BUILD_ROOT%{_localstatedir}/lib/dav

# create a prototype session cache
mkdir -p $RPM_BUILD_ROOT%{_localstatedir}/cache/mod_ssl
touch $RPM_BUILD_ROOT%{_localstatedir}/cache/mod_ssl/scache.{dir,pag,sem}

# move the build directory to within the library directory
mv $RPM_BUILD_ROOT%{contentdir}/build $RPM_BUILD_ROOT%{_libdir}/httpd/build

# Make the MMN accessible to module packages
echo %{mmn} > $RPM_BUILD_ROOT%{_includedir}/httpd/.mmn

# docroot
mkdir $RPM_BUILD_ROOT%{contentdir}/html

# Set up /var directories
rmdir $RPM_BUILD_ROOT%{_sysconfdir}/httpd/logs
mkdir -p $RPM_BUILD_ROOT%{_localstatedir}/log/httpd
mkdir -p $RPM_BUILD_ROOT%{_localstatedir}/cache/httpd/cache-root

# symlinks for /etc/httpd
ln -s ../..%{_localstatedir}/log/httpd $RPM_BUILD_ROOT/etc/httpd/logs
ln -s ../..%{_localstatedir}/run $RPM_BUILD_ROOT/etc/httpd/run
ln -s ../..%{_libdir}/httpd/modules $RPM_BUILD_ROOT/etc/httpd/modules

# install SYSV init stuff
mkdir -p $RPM_BUILD_ROOT/etc/rc.d/init.d
install -m755 ./build/rpm/httpd.init \
	$RPM_BUILD_ROOT/etc/rc.d/init.d/httpd
install -m755 ./build/rpm/htcacheclean.init \
        $RPM_BUILD_ROOT/etc/rc.d/init.d/htcacheclean

# install log rotation stuff
mkdir -p $RPM_BUILD_ROOT/etc/logrotate.d
install -m644 ./build/rpm/httpd.logrotate \
	$RPM_BUILD_ROOT/etc/logrotate.d/httpd

# Remove unpackaged files
rm -rf $RPM_BUILD_ROOT%{_libdir}/httpd/modules/*.exp \
       $RPM_BUILD_ROOT%{contentdir}/htdocs/* \
       $RPM_BUILD_ROOT%{contentdir}/cgi-bin/* 

# Make suexec a+rw so it can be stripped.  %%files lists real permissions
chmod 755 $RPM_BUILD_ROOT%{_sbindir}/suexec

%pre
# Add the "apache" user
/usr/sbin/useradd -c "Apache" -u 48 \
	-s /sbin/nologin -r -d %{contentdir} apache 2> /dev/null || :

%post
# Register the httpd service
/sbin/chkconfig --add httpd
/sbin/chkconfig --add htcacheclean

%preun
if [ $1 = 0 ]; then
	/sbin/service httpd stop > /dev/null 2>&1
        /sbin/service htcacheclean stop > /dev/null 2>&1
	/sbin/chkconfig --del httpd
        /sbin/chkconfig --del htcacheclean
fi

%post -n mod_ssl
umask 077

if [ ! -f %{_sysconfdir}/httpd/conf/ssl.key/server.key ] ; then
%{_bindir}/openssl genrsa -rand /proc/apm:/proc/cpuinfo:/proc/dma:/proc/filesystems:/proc/interrupts:/proc/ioports:/proc/pci:/proc/rtc:/proc/uptime 1024 > %{_sysconfdir}/httpd/conf/ssl.key/server.key 2> /dev/null
fi

FQDN=`hostname`
if [ "x${FQDN}" = "x" ]; then
   FQDN=localhost.localdomain
fi

if [ ! -f %{_sysconfdir}/httpd/conf/ssl.crt/server.crt ] ; then
cat << EOF | %{_bindir}/openssl req -new -key %{_sysconfdir}/httpd/conf/ssl.key/server.key -x509 -days 365 -out %{_sysconfdir}/httpd/conf/ssl.crt/server.crt 2>/dev/null
--
SomeState
SomeCity
SomeOrganization
SomeOrganizationalUnit
${FQDN}
root@${FQDN}
EOF
fi

%check
# Check the built modules are all PIC
if readelf -d $RPM_BUILD_ROOT%{_libdir}/httpd/modules/*.so | grep TEXTREL; then
   : modules contain non-relocatable code
   exit 1
fi

# Verify that the same modules were built into the httpd binaries
./prefork/httpd -l | grep -v prefork > prefork.mods
for mpm in %{mpms}; do
  ./${mpm}/httpd -l | grep -v ${mpm} > ${mpm}.mods
  if ! diff -u prefork.mods ${mpm}.mods; then
    : Different modules built into httpd binaries, will not proceed
    exit 1
  fi
done

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)

%doc ABOUT_APACHE README CHANGES LICENSE NOTICE

%dir %{_sysconfdir}/httpd
%{_sysconfdir}/httpd/modules
%{_sysconfdir}/httpd/logs
%{_sysconfdir}/httpd/run
%dir %{_sysconfdir}/httpd/conf
%config(noreplace) %{_sysconfdir}/httpd/conf/httpd.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/magic
%config(noreplace) %{_sysconfdir}/httpd/conf/mime.types
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-autoindex.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-dav.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-default.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-info.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-languages.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-manual.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-mpm.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-multilang-errordoc.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-userdir.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-vhosts.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-autoindex.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-dav.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-default.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-info.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-languages.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-manual.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-mpm.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-multilang-errordoc.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-userdir.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-vhosts.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/original/httpd.conf

%config %{_sysconfdir}/logrotate.d/httpd
%config %{_sysconfdir}/rc.d/init.d/httpd
%config %{_sysconfdir}/rc.d/init.d/htcacheclean

%{_sbindir}/ab
%{_sbindir}/htcacheclean
%{_sbindir}/htdbm
%{_sbindir}/htdigest
%{_sbindir}/htpasswd
%{_sbindir}/logresolve
%{_sbindir}/httpd
%{_sbindir}/httpd.worker
%{_sbindir}/httpd.event
%{_sbindir}/httxt2dbm
%{_sbindir}/apachectl
%{_sbindir}/rotatelogs
%attr(4510,root,%{suexec_caller}) %{_sbindir}/suexec

%dir %{_libdir}/httpd
%dir %{_libdir}/httpd/modules
# everything but mod_ssl.so:
%{_libdir}/httpd/modules/mod_[a-r]*.so
%{_libdir}/httpd/modules/mod_s[petu]*.so
%{_libdir}/httpd/modules/mod_[t-z]*.so

%dir %{contentdir}
%dir %{contentdir}/cgi-bin
%dir %{contentdir}/html
%dir %{contentdir}/icons
%dir %{contentdir}/error
%dir %{contentdir}/error/include
%{contentdir}/icons/*
%{contentdir}/error/README
%config(noreplace) %{contentdir}/error/*.var
%config(noreplace) %{contentdir}/error/include/*.html

%attr(0700,root,root) %dir %{_localstatedir}/log/httpd

%attr(0700,apache,apache) %dir %{_localstatedir}/lib/dav
%attr(0700,apache,apache) %dir %{_localstatedir}/cache/httpd/cache-root

%{_mandir}/man1/*
%{_mandir}/man8/ab*
%{_mandir}/man8/rotatelogs*
%{_mandir}/man8/logresolve*
%{_mandir}/man8/suexec*
%{_mandir}/man8/apachectl.8*
%{_mandir}/man8/httpd.8*
%{_mandir}/man8/htcacheclean.8*

%files manual
%defattr(-,root,root)
%{contentdir}/manual
%{contentdir}/error/README

%files -n mod_ssl
%defattr(-,root,root)
%{_libdir}/httpd/modules/mod_ssl.so
%config(noreplace) %{_sysconfdir}/httpd/conf/original/extra/httpd-ssl.conf
%config(noreplace) %{_sysconfdir}/httpd/conf/extra/httpd-ssl.conf
%attr(0700,apache,root) %dir %{_localstatedir}/cache/mod_ssl
%attr(0600,apache,root) %ghost %{_localstatedir}/cache/mod_ssl/scache.dir
%attr(0600,apache,root) %ghost %{_localstatedir}/cache/mod_ssl/scache.pag
%attr(0600,apache,root) %ghost %{_localstatedir}/cache/mod_ssl/scache.sem

%files devel
%defattr(-,root,root)
%{_includedir}/httpd
%{_sbindir}/apxs
%{_sbindir}/checkgid
%{_sbindir}/dbmmanage
%{_sbindir}/envvars*
%{_mandir}/man8/apxs.8*
%dir %{_libdir}/httpd/build
%{_libdir}/httpd/build/*.mk
%{_libdir}/httpd/build/instdso.sh
%{_libdir}/httpd/build/config.nice
%{_libdir}/httpd/build/mkdir.sh

%changelog
* Mon Mar 27 2006 Graham Leggett <minfrin@apache.org> 2.2.1-dev
- Update dependancies on apr and apr-util to at least v1.2.0.
- Add the missing file-cache module to the cache build.

* Fri Aug 26 2005 Graham Leggett <minfrin@apache.org> 2.1.7
- Deleting the xml doc files is no longer necessary.
- Add httxt2dbm to the sbin directory

* Sat Jul 2 2005 Graham Leggett <minfrin@apache.org> 2.1.7-dev
- Fixed complaints about unpackaged files with new config file changes.

* Thu Dec 16 2004 Graham Leggett <minfrin@apache.org> 2.1.3-dev
- Changed build to use external apr and apr-util

* Thu May 20 2004 Graham Leggett <minfrin@apache.org> 2.0.50-dev
- Changed default dependancy to link to db4 instead of db3.
- Fixed complaints about unpackaged files.

* Sat Apr 5 2003 Graham Leggett <minfrin@apache.org> 2.0.46-dev
- Moved mime.types back to the default location.
- Added mod_ldap and friends, mod_cache and friends.
- Added openldap dependancy.

* Sun Mar 30 2003 Graham Leggett <minfrin@apache.org> 2.0.45-1
- Created generic Apache rpm spec file from that donated by Redhat.
- Removed Redhat specific patches and boilerplate files.
- Removed SSL related Makefiles.

* Mon Feb 24 2003 Joe Orton <jorton@redhat.com> 2.0.40-21
- add security fix for CAN-2003-0020; replace non-printable characters
  with '!' when printing to error log.
- disable debuginfo on IA64.

* Tue Feb 11 2003 Joe Orton <jorton@redhat.com> 2.0.40-20
- disable POSIX semaphores to support 2.4.18 kernel (#83324)

* Wed Jan 29 2003 Joe Orton <jorton@redhat.com> 2.0.40-19
- require xmlto 0.0.11 or later
- fix apr_strerror on glibc2.3

* Wed Jan 22 2003 Tim Powers <timp@redhat.com> 2.0.40-18
- rebuilt

* Thu Jan 16 2003 Joe Orton <jorton@redhat.com> 2.0.40-17
- add mod_cgid and httpd binary built with worker MPM (#75496)
- allow choice of httpd binary in init script
- pick appropriate CGI module based on loaded MPM in httpd.conf
- source /etc/sysconfig/httpd in apachectl to get httpd choice
- make "apachectl status" fail gracefully when links isn't found (#78159)

* Mon Jan 13 2003 Joe Orton <jorton@redhat.com> 2.0.40-16
- rebuild for OpenSSL 0.9.7

* Fri Jan  3 2003 Joe Orton <jorton@redhat.com> 2.0.40-15
- fix possible infinite recursion in config dir processing (#77206)
- fix memory leaks in request body processing (#79282)

* Thu Dec 12 2002 Joe Orton <jorton@redhat.com> 2.0.40-14
- remove unstable shmht session cache from mod_ssl
- get SSL libs from pkg-config if available (Nalin Dahyabhai)
- stop "apxs -a -i" from inserting AddModule into httpd.conf (#78676)

* Wed Nov  6 2002 Joe Orton <jorton@redhat.com> 2.0.40-13
- fix location of installbuilddir in apxs when libdir!=/usr/lib

* Wed Nov  6 2002 Joe Orton <jorton@redhat.com> 2.0.40-12
- pass libdir to configure; clean up config_vars.mk
- package instdso.sh, fixing apxs -i (#73428)
- prevent build if upstream MMN differs from mmn macro
- remove installed but unpackaged files

* Wed Oct  9 2002 Joe Orton <jorton@redhat.com> 2.0.40-11
- correct SERVER_NAME encoding in i18n error pages (thanks to Andre Malo)

* Wed Oct  9 2002 Joe Orton <jorton@redhat.com> 2.0.40-10
- fix patch for CAN-2002-0840 to also cover i18n error pages

* Wed Oct  2 2002 Joe Orton <jorton@redhat.com> 2.0.40-9
- security fixes for CAN-2002-0840 and CAN-2002-0843
- fix for possible mod_dav segfault for certain requests

* Tue Sep 24 2002 Gary Benson <gbenson@redhat.com>
- updates to the migration guide

* Wed Sep  4 2002 Nalin Dahyabhai <nalin@redhat.com> 2.0.40-8
- link httpd with libssl to avoid library loading/unloading weirdness

* Tue Sep  3 2002 Joe Orton <jorton@redhat.com> 2.0.40-7
- add LoadModule lines for proxy modules in httpd.conf (#73349)
- fix permissions of conf/ssl.*/ directories; add Makefiles for
  certificate management (#73352)

* Mon Sep  2 2002 Joe Orton <jorton@redhat.com> 2.0.40-6
- provide "httpd-mmn" to manage module ABI compatibility

* Sun Sep  1 2002 Joe Orton <jorton@redhat.com> 2.0.40-5
- fix SSL session cache (#69699)
- revert addition of LDAP support to apr-util

* Mon Aug 26 2002 Joe Orton <jorton@redhat.com> 2.0.40-4
- set SIGXFSZ disposition to "ignored" (#69520)
- make dummy connections to the first listener in config (#72692)

* Mon Aug 26 2002 Joe Orton <jorton@redhat.com> 2.0.40-3
- allow "apachectl configtest" on a 1.3 httpd.conf
- add mod_deflate
- enable LDAP support in apr-util
- don't package everything in /var/www/error as config(noreplace)

* Wed Aug 21 2002 Bill Nottingham <notting@redhat.com> 2.0.40-2
- add trigger (#68657)

* Mon Aug 12 2002 Joe Orton <jorton@redhat.com> 2.0.40-1
- update to 2.0.40

* Wed Jul 24 2002 Joe Orton <jorton@redhat.com> 2.0.36-8
- improve comment on use of UserDir in default config (#66886)

* Wed Jul 10 2002 Joe Orton <jorton@redhat.com> 2.0.36-7
- use /sbin/nologin as shell for apache user (#68371)
- add patch from CVS to fix possible infinite loop when processing
  internal redirects

* Wed Jun 26 2002 Gary Benson <gbenson@redhat.com> 2.0.36-6
- modify init script to detect 1.3.x httpd.conf's and direct users
  to the migration guide

* Tue Jun 25 2002 Gary Benson <gbenson@redhat.com> 2.0.36-5
- patch apachectl to detect 1.3.x httpd.conf's and direct users
  to the migration guide
- ship the migration guide

* Fri Jun 21 2002 Joe Orton <jorton@redhat.com>
- move /etc/httpd2 back to /etc/httpd
- add noindex.html page and poweredby logo; tweak default config
  to load noindex.html if no default "/" page is present.
- add patch to prevent mutex errors on graceful restart

* Fri Jun 21 2002 Tim Powers <timp@redhat.com> 2.0.36-4
- automated rebuild

* Wed Jun 12 2002 Joe Orton <jorton@redhat.com> 2.0.36-3
- add patch to fix SSL mutex handling

* Wed Jun 12 2002 Joe Orton <jorton@redhat.com> 2.0.36-2
- improved config directory patch

* Mon May 20 2002 Joe Orton <jorton@redhat.com>
- initial build; based heavily on apache.spec and mod_ssl.spec
- fixes: #65214, #58490, #57376, #61265, #65518, #58177, #57245
