#!/usr/bin/env python
#-*- coding: ascii -*-

# ShaderConductor
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import multiprocessing, os, platform, subprocess, sys

def LogError(message):
	print(f"[E] {message}")
	sys.stdout.flush()
	pauseCmd = "pause" if sys.platform.find("win") == 0 else "read"
	subprocess.call(pauseCmd, shell = True)
	sys.exit(1)

def LogInfo(message):
	print(f"[I] {message}")
	sys.stdout.flush()

def LogWarning(message):
	print(f"[W] {message}")
	sys.stdout.flush()

def FindProgramFilesFolder():
	env = os.environ
	return (
		env.get("ProgramFiles(x86)", "C:\Program Files (x86)")
		if platform.architecture()[0] == "64bit"
		else env.get("ProgramFiles", "C:\Program Files")
	)

def FindVS2017OrUpFolder(programFilesFolder, vsVersion, vsName):
	tryVswhereLocation = programFilesFolder + "\\Microsoft Visual Studio\\Installer\\vswhere.exe"
	tryVcvarsall = "VCVARSALL.BAT"
	if os.path.exists(tryVswhereLocation):
		vsLocation = subprocess.check_output([tryVswhereLocation,
			"-latest",
			"-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
			"-property", "installationPath",
			"-version", "[%d.0,%d.0)" % (vsVersion, vsVersion + 1),
			"-prerelease"]).decode().split("\r\n")[0]
		tryFolder = vsLocation + "\\VC\\Auxiliary\\Build\\"
		if os.path.exists(tryFolder + tryVcvarsall):
			return tryFolder
	else:
		names = ("Preview", vsName)
		skus = ("Community", "Professional", "Enterprise")
		for name in names:
			for sku in skus:
				tryFolder = programFilesFolder + "\\Microsoft Visual Studio\\%s\\%s\\VC\\Auxiliary\\Build\\" % (name, sku)
				if os.path.exists(tryFolder + tryVcvarsall):
					return tryFolder
	LogError("Could NOT find VS%s.\n" % vsName)
	return ""

def FindVS2019Folder(programFilesFolder):
	return FindVS2017OrUpFolder(programFilesFolder, 16, "2019")

def FindVS2017Folder(programFilesFolder):
	return FindVS2017OrUpFolder(programFilesFolder, 15, "2017")

def FindVS2015Folder(programFilesFolder):
	env = os.environ
	if "VS140COMNTOOLS" in env:
		return env["VS140COMNTOOLS"] + "..\\..\\VC\\"
	tryFolder = programFilesFolder + "\\Microsoft Visual Studio 14.0\\VC\\"
	tryVcvarsall = "VCVARSALL.BAT"
	if os.path.exists(tryFolder + tryVcvarsall):
		return tryFolder
	else:
		LogError("Could NOT find VS2015.\n")

class BatchCommand:
	def __init__(self, hostPlatform):
		self.commands = []
		self.hostPlatform = hostPlatform

	def AddCommand(self, cmd):
		self.commands += [cmd]

	def Execute(self):
		batchFileName = "scBuild." + ("bat" if self.hostPlatform == "win" else "sh")
		with open(batchFileName, "w") as batchFile:
			batchFile.writelines([cmd_line + "\n" for cmd_line in self.commands])
		if self.hostPlatform == "win":
			retCode = subprocess.call(batchFileName, shell = True)
		else:
			subprocess.call(f"chmod 777 {batchFileName}", shell = True)
			retCode = subprocess.call(f"./{batchFileName}", shell = True)
		os.remove(batchFileName)
		return retCode

def Build(hostPlatform, hostArch, buildSys, compiler, arch, configuration, tblgenMode, tblgenPath):
	originalDir = os.path.abspath(os.curdir)

	if not os.path.exists("Build"):
		os.mkdir("Build")

	multiConfig = (buildSys.find("vs") == 0)

	buildDir = f"Build/{buildSys}-{hostPlatform}-{compiler}-{arch}"
	if (not multiConfig) or (configuration == "clangformat"):
		buildDir += f"-{configuration}";
	if not os.path.exists(buildDir):
		os.mkdir(buildDir)
	os.chdir(buildDir)
	buildDir = os.path.abspath(os.curdir)

	tblgenOptions = ""
	if (tblgenPath != None):
		tblgenOptions = " -DCLANG_TABLEGEN=\"%s\" -DLLVM_TABLEGEN=\"%s\"" % tblgenPath

	parallel = multiprocessing.cpu_count()

	batCmd = BatchCommand(hostPlatform)
	if hostPlatform == "win":
		programFilesFolder = FindProgramFilesFolder()
		if (buildSys == "vs2019") or ((buildSys == "ninja") and (compiler == "vc142")):
			vsFolder = FindVS2019Folder(programFilesFolder)
		elif (buildSys == "vs2017") or ((buildSys == "ninja") and (compiler == "vc141")):
			vsFolder = FindVS2017Folder(programFilesFolder)
		elif (buildSys == "vs2015") or ((buildSys == "ninja") and (compiler == "vc140")):
			vsFolder = FindVS2015Folder(programFilesFolder)
		if arch == "x64":
			vcOption = "amd64"
			vcArch = "x64"
		elif arch == "x86":
			vcOption = "x86"
			vcArch = "Win32"
		elif arch == "arm64":
			vcOption = "amd64_arm64"
			vcArch = "ARM64"
		elif arch == "arm":
			vcOption = "amd64_arm"
			vcArch = "ARM"
		else:
			LogError("Unsupported architecture.\n")
		vcToolset = ""
		if (buildSys == "vs2019") and (compiler == "vc141"):
			vcOption += " -vcvars_ver=14.1"
			vcToolset = "v141,"
		elif buildSys in ["vs2019", "vs2017"] and compiler == "vc140":
			vcOption += " -vcvars_ver=14.0"
			vcToolset = "v140,"
		batCmd.AddCommand("@call \"%sVCVARSALL.BAT\" %s" % (vsFolder, vcOption))
		batCmd.AddCommand("@cd /d \"%s\"" % buildDir)
	if (buildSys == "ninja"):
		if hostPlatform == "win":
			batCmd.AddCommand("set CC=cl.exe")
			batCmd.AddCommand("set CXX=cl.exe")
		if (configuration == "clangformat"):
			options = "-DSC_CLANGFORMAT=\"ON\""
		else:
			options = "-DCMAKE_BUILD_TYPE=\"%s\" -DSC_ARCH_NAME=\"%s\" %s" % (configuration, arch, tblgenOptions)
		batCmd.AddCommand(f"cmake -G Ninja {options} ../../")
		if tblgenMode:
			batCmd.AddCommand("ninja clang-tblgen -j%d" % parallel)
			batCmd.AddCommand("ninja llvm-tblgen -j%d" % parallel)
		else:
			batCmd.AddCommand("ninja -j%d" % parallel)
	else:
		if buildSys == "vs2019":
			generator = "\"Visual Studio 16\""
		elif buildSys == "vs2017":
			generator = "\"Visual Studio 15\""
		elif buildSys == "vs2015":
			generator = "\"Visual Studio 14\""
		if (configuration == "clangformat"):
			cmake_options = "-DSC_CLANGFORMAT=\"ON\""
			msbuild_options = ""
		else:
			cmake_options = f"-T {vcToolset}host=x64 -A {vcArch} {tblgenOptions}"
			msbuild_options = "/m:%d /v:m /p:Configuration=%s,Platform=%s" % (parallel, configuration, vcArch)
		batCmd.AddCommand(f"cmake -G {generator} {cmake_options} ../../")
		if tblgenMode:
			batCmd.AddCommand("MSBuild External\\DirectXShaderCompiler\\tools\\clang\\utils\\TableGen\\clang-tblgen.vcxproj /nologo %s" % msbuild_options)
			batCmd.AddCommand("MSBuild External\\DirectXShaderCompiler\\utils\\TableGen\\llvm-tblgen.vcxproj /nologo %s" % msbuild_options)
		else:
			batCmd.AddCommand(f"MSBuild ALL_BUILD.vcxproj /nologo {msbuild_options}")
	if batCmd.Execute() != 0:
		LogError("Build failed.\n")

	os.chdir(originalDir)

	tblGenPath = f"{buildDir}/External/DirectXShaderCompiler"
	if multiConfig:
		tblGenPath += f"/{configuration}"
	tblGenPath += "/bin/"
	clangTblgenPath = f"{tblGenPath}clang-tblgen"
	llvmTblGenPath = f"{tblGenPath}llvm-tblgen"
	if (hostPlatform == "win"):
		clangTblgenPath += ".exe"
		llvmTblGenPath += ".exe"
	return (clangTblgenPath, llvmTblGenPath)

if __name__ == "__main__":
	hostPlatform = sys.platform
	if hostPlatform.find("win") == 0:
		hostPlatform = "win"
	elif hostPlatform.find("linux") == 0:
		hostPlatform = "linux"
	elif hostPlatform.find("darwin") == 0:
		hostPlatform = "osx"

	hostArch = platform.machine()
	if hostArch in ["AMD64", "x86_64"]:
		hostArch = "x64"
	elif (hostArch == "i386"):
		hostArch = "x86"
	elif (hostArch == "ARM64"):
		hostArch = "arm64"
	else:
		LogError("Unknown host architecture %s.\n" % hostArch)

	argc = len(sys.argv);
	if (argc > 1):
		buildSys = sys.argv[1]
	else:
		buildSys = "vs2019" if hostPlatform == "win" else "ninja"
	if (argc > 2):
		compiler = sys.argv[2]
	elif buildSys == "vs2015":
		compiler = "vc140"
	elif buildSys == "vs2017":
		compiler = "vc141"
	elif buildSys == "vs2019":
		compiler = "vc142"
	else:
		compiler = "gcc"
	arch = sys.argv[3] if (argc > 3) else "x64"
	configuration = sys.argv[4] if (argc > 4) else "Release"
	tblgenPath = None
	if (
		configuration != "clangformat"
		and hostArch != arch
		and (hostArch != "x64" or arch != "x86")
	):
		# Cross compiling:
		# Generate a project with host architecture, build clang-tblgen and llvm-tblgen, and keep the path of clang-tblgen and llvm-tblgen
		tblgenPath = Build(hostPlatform, hostArch, buildSys, compiler, hostArch, configuration, True, None)

	Build(hostPlatform, hostArch, buildSys, compiler, arch, configuration, False, tblgenPath)
