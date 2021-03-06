#!/usr/bin/env python

'''
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''
import sys
from ambari_commons.os_family_impl import OsFamilyImpl, OsFamilyFuncImpl

# For compatibility with different OSes
# Edit PYTHONPATH to be able to import common_functions
sys.path.append("/usr/lib/python2.6/site-packages/")
import os
import string
import subprocess
import logging
import shutil
import platform
import fnmatch
import ConfigParser
import optparse
import shlex
import datetime
from AmbariConfig import AmbariConfig
from ambari_commons import OSCheck, OSConst
from ambari_commons.constants import AMBARI_SUDO_BINARY


logger = logging.getLogger()

PACKAGE_ERASE_CMD = {
  "redhat": "yum erase -y {0}",
  "suse": "zypper -n -q remove {0}",
  "ubuntu": "/usr/bin/apt-get -y -q remove {0}"
}

USER_ERASE_CMD = "userdel -rf {0}"
GROUP_ERASE_CMD = "groupdel {0}"
PROC_KILL_CMD = "kill -9 {0}"
ALT_DISP_CMD = "alternatives --display {0}"
ALT_ERASE_CMD = "alternatives --remove {0} {1}"

REPO_PATH_RHEL = "/etc/yum.repos.d"
REPO_PATH_SUSE = "/etc/zypp/repos.d/"
SKIP_LIST = []
TMP_HOST_CHECK_FILE_NAME = "tmp_hostcheck.result"
HOST_CHECK_FILE_NAME = "hostcheck.result"
HOST_CHECK_CUSTOM_ACTIONS_FILE = "hostcheck_custom_actions.result"
OUTPUT_FILE_NAME = "hostcleanup.result"

PACKAGE_SECTION = "packages"
PACKAGE_KEY = "pkg_list"
USER_SECTION = "users"
USER_KEY = "usr_list"
USER_HOMEDIR_KEY = "usr_homedir_list"
USER_HOMEDIR_SECTION = "usr_homedir"
REPO_SECTION = "repositories"
REPOS_KEY = "repo_list"
DIR_SECTION = "directories"
ADDITIONAL_DIRS = "additional_directories"
DIR_KEY = "dir_list"
CACHE_FILES_PATTERN = {
  'alerts': ['*.json']
}
PROCESS_SECTION = "processes"
PROCESS_KEY = "proc_list"
ALT_SECTION = "alternatives"
ALT_KEYS = ["symlink_list", "target_list"]
HADOOP_GROUP = "hadoop"
FOLDER_LIST = ["/tmp"]
# Additional path patterns to find existing directory
DIRNAME_PATTERNS = [
    "/tmp/hadoop-", "/tmp/hsperfdata_"
]

# resources that should not be cleaned
REPOSITORY_BLACK_LIST = ["ambari.repo"]
PACKAGES_BLACK_LIST = ["ambari-server", "ambari-agent"]

class HostCleanup:

  SELECT_ALL_PERFORMED_MARKER = "/var/lib/ambari-agent/data/hdp-select-set-all.performed"

  def resolve_ambari_config(self):
    try:
      config = AmbariConfig()
      if os.path.exists(AmbariConfig.getConfigFile()):
        config.read(AmbariConfig.getConfigFile())
      else:
        raise Exception("No config found, use default")

    except Exception, err:
      logger.warn(err)
    return config

  def get_additional_dirs(self):
    resultList = []
    dirList = set()
    for patern in DIRNAME_PATTERNS:
      dirList.add(os.path.dirname(patern))

    for folder in dirList:
      for dirs in os.walk(folder):
        for dir in dirs:
          for patern in DIRNAME_PATTERNS:
            if patern in dir:
             resultList.append(dir)
    return resultList

  def do_cleanup(self, argMap=None):
    if argMap:
      packageList = argMap.get(PACKAGE_SECTION)
      userList = argMap.get(USER_SECTION)
      homeDirList = argMap.get(USER_HOMEDIR_SECTION)
      dirList = argMap.get(DIR_SECTION)
      repoList = argMap.get(REPO_SECTION)
      procList = argMap.get(PROCESS_SECTION)
      alt_map = argMap.get(ALT_SECTION)
      additionalDirList = self.get_additional_dirs()

      if userList and not USER_SECTION in SKIP_LIST:
        userIds = self.get_user_ids(userList)
      if procList and not PROCESS_SECTION in SKIP_LIST:
        logger.info("\n" + "Killing pid's: " + str(procList) + "\n")
        self.do_kill_processes(procList)
      if packageList and not PACKAGE_SECTION in SKIP_LIST:
        logger.info("Deleting packages: " + str(packageList) + "\n")
        self.do_erase_packages(packageList)
        # Removing packages means that we have to rerun hdp-select
        self.do_remove_hdp_select_marker()
      if userList and not USER_SECTION in SKIP_LIST:
        logger.info("\n" + "Deleting users: " + str(userList))
        self.do_delete_users(userList)
        self.do_erase_dir_silent(homeDirList)
        self.do_delete_by_owner(userIds, FOLDER_LIST)
      if dirList and not DIR_SECTION in SKIP_LIST:
        logger.info("\n" + "Deleting directories: " + str(dirList))
        self.do_erase_dir_silent(dirList)
      if additionalDirList and not ADDITIONAL_DIRS in SKIP_LIST:
        logger.info("\n" + "Deleting additional directories: " + str(dirList))
        self.do_erase_dir_silent(additionalDirList)
      if repoList and not REPO_SECTION in SKIP_LIST:
        repoFiles = self.find_repo_files_for_repos(repoList)
        logger.info("\n" + "Deleting repo files: " + str(repoFiles))
        self.do_erase_files_silent(repoFiles)
      if alt_map and not ALT_SECTION in SKIP_LIST:
        logger.info("\n" + "Erasing alternatives:" + str(alt_map) + "\n")
        self.do_erase_alternatives(alt_map)

    return 0

  def read_host_check_file(self, config_file_path):
    propertyMap = {}
    try:
      with open(config_file_path, 'r'):
        pass
    except Exception, e:
      logger.error("Host check result not found at: " + str(config_file_path))
      return None

    try:
      config = ConfigParser.RawConfigParser()
      config.read(config_file_path)
    except Exception, e:
      logger.error("Cannot read host check result: " + str(e))
      return None

    # Initialize map from file
    try:
      if config.has_option(PACKAGE_SECTION, PACKAGE_KEY):
        propertyMap[PACKAGE_SECTION] = config.get(PACKAGE_SECTION, PACKAGE_KEY).split(',')
    except:
      logger.warn("Cannot read package list: " + str(sys.exc_info()[0]))
    try:
      if config.has_option(PROCESS_SECTION, PROCESS_KEY):
        propertyMap[PROCESS_SECTION] = config.get(PROCESS_SECTION, PROCESS_KEY).split(',')
    except:
        logger.warn("Cannot read process list: " + str(sys.exc_info()[0]))
    try:
      if config.has_option(USER_SECTION, USER_KEY):
        propertyMap[USER_SECTION] = config.get(USER_SECTION, USER_KEY).split(',')
    except:
      logger.warn("Cannot read user list: " + str(sys.exc_info()[0]))

    try:
      if config.has_option(USER_SECTION, USER_HOMEDIR_KEY):
        propertyMap[USER_HOMEDIR_SECTION] = config.get(USER_SECTION, USER_HOMEDIR_KEY).split(',')
    except:
      logger.warn("Cannot read user homedir list: " + str(sys.exc_info()[0]))

    try:
      if config.has_option(REPO_SECTION, REPOS_KEY):
        propertyMap[REPO_SECTION] = config.get(REPO_SECTION, REPOS_KEY).split(',')
    except:
      logger.warn("Cannot read repositories list: " + str(sys.exc_info()[0]))

    try:
      if config.has_option(DIR_SECTION, DIR_KEY):
        propertyMap[DIR_SECTION] = config.get(DIR_SECTION, DIR_KEY).split(',')
    except:
      logger.warn("Cannot read dir list: " + str(sys.exc_info()[0]))

    try:
      alt_map = {}
      if config.has_option(ALT_SECTION, ALT_KEYS[0]):
        alt_map[ALT_KEYS[0]] = config.get(ALT_SECTION, ALT_KEYS[0]).split(',')
      if config.has_option(ALT_SECTION, ALT_KEYS[1]):
        alt_map[ALT_KEYS[1]] = config.get(ALT_SECTION, ALT_KEYS[1]).split(',')
      if alt_map:
        propertyMap[ALT_SECTION] = alt_map
    except:
      logger.warn("Cannot read alternates list: " + str(sys.exc_info()[0]))

    return propertyMap

  def get_alternatives_desc(self, alt_name):
    command = ALT_DISP_CMD.format(alt_name)
    out = None
    try:
      p1 = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE)
      p2 = subprocess.Popen(["grep", "priority"], stdin=p1.stdout, stdout=subprocess.PIPE)
      p1.stdout.close()
      out = p2.communicate()[0]
      logger.debug('alternatives --display ' + alt_name + '\n, out = ' + out)
    except:
      logger.warn('Cannot process alternative named: ' + alt_name + ',' + \
                  'error: ' + str(sys.exc_info()[0]))

    return out


  def do_clear_cache(self, cache_root, dir_map=None):
    """
     Clear cache dir according to provided root directory

     cache_root - root dir for cache directory
     dir_map - should be used only for recursive calls
    """
    global CACHE_FILES_PATTERN
    file_map = CACHE_FILES_PATTERN if dir_map is None else dir_map
    remList = []

    # Build remove list according to masks
    for folder in file_map:
      if isinstance(file_map[folder], list):  # here is list of file masks/files
        for mask in file_map[folder]:
          remList += self.get_files_in_dir("%s/%s" % (cache_root, folder), mask)
      elif isinstance(file_map[folder], dict):  # here described sub-folder
        remList += self.do_clear_cache("%s/%s" % (cache_root, folder), file_map[folder])

    if dir_map is not None:  # push result list back as this is call from stack
      return remList
    else:  # root call, so we have final list
      self.do_erase_files_silent(remList)


  def do_remove_hdp_select_marker(self):
    """
    Remove marker file for 'hdp-select set all' invocation
    """
    if os.path.isfile(self.SELECT_ALL_PERFORMED_MARKER):
      os.unlink(self.SELECT_ALL_PERFORMED_MARKER)


  # Alternatives exist as a stack of symlinks under /var/lib/alternatives/$name
  # Script expects names of the alternatives as input
  # We find all the symlinks using command, #] alternatives --display $name
  # and delete them using command, #] alternatives --remove $name $path.
  def do_erase_alternatives(self, alt_map):
    if alt_map:
      alt_list = alt_map.get(ALT_KEYS[0])
      if alt_list:
        for alt_name in alt_list:
          if alt_name:
            out = self.get_alternatives_desc(alt_name)

            if not out:
              logger.warn('No alternatives found for: ' + alt_name)
              continue
            else:
              alternates = out.split('\n')
              if alternates:
                for entry in alternates:
                  if entry:
                    alt_path = entry.split()[0]
                    logger.debug('Erasing alternative named: ' + alt_name + ', ' \
                                                                            'path: ' + alt_path)

                    command = ALT_ERASE_CMD.format(alt_name, alt_path)
                    (returncode, stdoutdata, stderrdata) = self.run_os_command(command)
                    if returncode != 0:
                      logger.warn('Failed to remove alternative: ' + alt_name +
                                  ", path: " + alt_path + ", error: " + stderrdata)

      # Remove directories - configs
      dir_list = alt_map.get(ALT_KEYS[1])
      if dir_list:
        self.do_erase_dir_silent(dir_list)

    return 0

  def do_kill_processes(self, pidList):
    if pidList:
      for pid in pidList:
        if pid:
          command = PROC_KILL_CMD.format(pid)
          (returncode, stdoutdata, stderrdata) = self.run_os_command(command)
          if returncode != 0:
            logger.error("Unable to kill process with pid: " + pid + ", " + stderrdata)
    return 0

  def get_files_in_dir(self, dirPath, filemask = None):
    fileList = []
    if dirPath:
      if os.path.exists(dirPath):
        listdir = os.listdir(dirPath)
        if listdir:
          for link in listdir:
            path = dirPath + os.sep + link
            if not os.path.islink(path) and not os.path.isdir(path):
              if filemask is not None:
                if fnmatch.fnmatch(path, filemask):
                  fileList.append(path)
              else:
                fileList.append(path)

    return fileList

  def find_repo_files_for_repos(self, repoNames):
    repoFiles = []
    osType = OSCheck.get_os_family()
    repoNameList = []
    for repoName in repoNames:
      if len(repoName.strip()) > 0:
        repoNameList.append("[" + repoName + "]")
        repoNameList.append("name=" + repoName)
    if repoNameList:
      # get list of files
      if osType == 'suse':
        fileList = self.get_files_in_dir(REPO_PATH_SUSE)
      elif osType == "redhat":
        fileList = self.get_files_in_dir(REPO_PATH_RHEL)
      else:
        logger.warn("Unsupported OS type, cannot get repository location.")
        return []

      if fileList:
        for filePath in fileList:
          with open(filePath, 'r') as file:
            content = file.readline()
            while (content != "" ):
              for repoName in repoNameList:
                if content.find(repoName) == 0 and filePath not in repoFiles:
                  repoFiles.append(filePath)
                  break;
              content = file.readline()

    return repoFiles

  def do_erase_packages(self, packageList):
    packageStr = None
    if packageList:
      packageStr = ' '.join(packageList)
      logger.debug("Erasing packages: " + packageStr)
    if packageStr is not None and packageStr:
      os_name = OSCheck.get_os_family()
      command = ''
      if os_name in PACKAGE_ERASE_CMD:
        command = PACKAGE_ERASE_CMD[os_name].format(packageStr)
      else:
        logger.warn("Unsupported OS type, cannot remove package.")

      if command != '':
        logger.debug('Executing: ' + str(command))
        (returncode, stdoutdata, stderrdata) = self.run_os_command(command)
        if returncode != 0:
          logger.warn("Erasing packages failed: " + stderrdata)
        else:
          logger.info("Erased packages successfully.\n" + stdoutdata)
    return 0

  def do_erase_dir_silent(self, pathList):
    if pathList:
      for path in pathList:
        if path and os.path.exists(path):
          if os.path.isdir(path):
            try:
              shutil.rmtree(path)
            except:
              logger.warn("Failed to remove dir: " + path + ", error: " + str(sys.exc_info()[0]))
          else:
            logger.info(path + " is a file and not a directory, deleting file")
            self.do_erase_files_silent([path])
        else:
          logger.info("Path doesn't exists: " + path)
    return 0

  def do_erase_files_silent(self, pathList):
    if pathList:
      for path in pathList:
        if path and os.path.exists(path):
          try:
            os.remove(path)
          except:
            logger.warn("Failed to delete file: " + path + ", error: " + str(sys.exc_info()[0]))
        else:
          logger.info("File doesn't exists: " + path)
    return 0

  def do_delete_group(self):
    groupDelCommand = GROUP_ERASE_CMD.format(HADOOP_GROUP)
    (returncode, stdoutdata, stderrdata) = self.run_os_command(groupDelCommand)
    if returncode != 0:
      logger.warn("Cannot delete group : " + HADOOP_GROUP + ", " + stderrdata)
    else:
      logger.info("Successfully deleted group: " + HADOOP_GROUP)

  def do_delete_by_owner(self, userIds, folders):
    for folder in folders:
      for filename in os.listdir(folder):
        fileToCheck = os.path.join(folder, filename)
        stat = os.stat(fileToCheck)
        if stat.st_uid in userIds:
          self.do_erase_dir_silent([fileToCheck])
          logger.info("Deleting file/folder: " + fileToCheck)

  @OsFamilyFuncImpl(os_family=OSConst.WINSRV_FAMILY)
  def get_user_ids(self, userList):

    userIds = []
    # No user ids to check in Windows for now
    return userIds

  @OsFamilyFuncImpl(os_family=OsFamilyImpl.DEFAULT)
  def get_user_ids(self, userList):
    from pwd import getpwnam

    userIds = []
    if userList:
      for user in userList:
        if user:
          try:
            userIds.append(getpwnam(user).pw_uid)
          except Exception:
            logger.warn("Cannot find user : " + user)
    return userIds

  def do_delete_users(self, userList):
    if userList:
      for user in userList:
        if user:
          command = USER_ERASE_CMD.format(user)
          (returncode, stdoutdata, stderrdata) = self.run_os_command(command)
          if returncode != 0:
            logger.warn("Cannot delete user : " + user + ", " + stderrdata)
          else:
            logger.info("Successfully deleted user: " + user)
      self.do_delete_group()
    return 0

  def is_current_user_root(self):
    return os.getuid() == 0

  # Run command as sudoer by default, if root no issues
  def run_os_command(self, cmd, runWithSudo=True):
    if runWithSudo:
      cmd = AMBARI_SUDO_BINARY + cmd
    logger.info('Executing command: ' + str(cmd))
    if type(cmd) == str:
      cmd = shlex.split(cmd)
    process = subprocess.Popen(cmd,
                               stdout=subprocess.PIPE,
                               stdin=subprocess.PIPE,
                               stderr=subprocess.PIPE
    )
    (stdoutdata, stderrdata) = process.communicate()
    return process.returncode, stdoutdata, stderrdata

# Copy file and save with file.# (timestamp)
def backup_file(filePath):
  if filePath is not None and os.path.exists(filePath):
    timestamp = datetime.datetime.now()
    format = '%Y%m%d%H%M%S'
    try:
      shutil.copyfile(filePath, filePath + "." + timestamp.strftime(format))
    except (Exception), e:
      logger.warn('Could not backup file "%s": %s' % (str(filePath, e)))
  return 0


def get_YN_input(prompt, default):
  yes = set(['yes', 'ye', 'y'])
  no = set(['no', 'n'])
  return get_choice_string_input(prompt, default, yes, no)


def get_choice_string_input(prompt, default, firstChoice, secondChoice):
  choice = raw_input(prompt).lower()
  if choice in firstChoice:
    return True
  elif choice in secondChoice:
    return False
  elif choice is "": # Just enter pressed
    return default
  else:
    print "input not recognized, please try again: "
    return get_choice_string_input(prompt, default, firstChoice, secondChoice)
  pass


def main():
  h = HostCleanup()
  config = h.resolve_ambari_config()
  hostCheckFileDir = config.get('agent', 'prefix')
  hostCheckFilePath = os.path.join(hostCheckFileDir, HOST_CHECK_FILE_NAME)
  hostCheckCustomActionsFilePath = os.path.join(hostCheckFileDir, HOST_CHECK_CUSTOM_ACTIONS_FILE)
  hostCheckFilesPaths = hostCheckFilePath + "," + hostCheckCustomActionsFilePath
  hostCheckResultPath = os.path.join(hostCheckFileDir, OUTPUT_FILE_NAME)

  parser = optparse.OptionParser()
  parser.add_option("-v", "--verbose", dest="verbose", action="store_false",
                    default=False, help="output verbosity.")
  parser.add_option("-f", "--file", dest="inputfiles",
                    default=hostCheckFilesPaths,
                    help="host check result file to read.", metavar="FILE")
  parser.add_option("-o", "--out", dest="outputfile",
                    default=hostCheckResultPath,
                    help="log file to store results.", metavar="FILE")
  parser.add_option("-k", "--skip", dest="skip",
                    help="(packages|users|directories|repositories|processes|alternatives)." + \
                         " Use , as separator.")
  parser.add_option("-s", "--silent",
                    action="store_true", dest="silent", default=False,
                    help="Silently accepts default prompt values")


  (options, args) = parser.parse_args()
  # set output file
  backup_file(options.outputfile)
  global logger
  logger = logging.getLogger('HostCleanup')
  handler = logging.FileHandler(options.outputfile)
  formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
  handler.setFormatter(formatter)
  logger.addHandler(handler)


  # set verbose
  if options.verbose:
    logging.basicConfig(level=logging.DEBUG)
  else:
    logging.basicConfig(level=logging.INFO)

  if options.skip is not None:
    global SKIP_LIST
    SKIP_LIST = options.skip.split(',')

  is_root = h.is_current_user_root()
  if not is_root:
    raise RuntimeError('HostCleanup needs to be run as root.')

  if not options.silent:
    if "users" not in SKIP_LIST:
      delete_users = get_YN_input('You have elected to remove all users as well. If it is not intended then use '
                               'option --skip \"users\". Do you want to continue [y/n] (y)', True)
      if not delete_users:
        print 'Exiting. Use option --skip="users" to skip deleting users'
        sys.exit(1)

  hostcheckfile, hostcheckfileca  = options.inputfiles.split(",")
  
  with open(TMP_HOST_CHECK_FILE_NAME, "wb") as tmp_f:
    with open(hostcheckfile, "rb") as f1:
      with open(hostcheckfileca, "rb") as f2:
        tmp_f.write(f1.read())
        tmp_f.write(f2.read())
  
  propMap = h.read_host_check_file(TMP_HOST_CHECK_FILE_NAME)

  if propMap:
    h.do_cleanup(propMap)

  if os.path.exists(config.get('agent', 'cache_dir')):
    h.do_clear_cache(config.get('agent', 'cache_dir'))

  logger.info('Clean-up completed. The output is at %s' % (str(options.outputfile)))


if __name__ == '__main__':
  main()
