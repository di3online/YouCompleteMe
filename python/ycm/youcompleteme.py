#!/usr/bin/env python
#
# Copyright (C) 2011, 2012  Strahinja Val Markovic  <val@markovic.io>
#
# This file is part of YouCompleteMe.
#
# YouCompleteMe is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# YouCompleteMe is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with YouCompleteMe.  If not, see <http://www.gnu.org/licenses/>.

import os
import vim
import ycm_core
import subprocess
import threading
from ycm.retries import retries
from ycm import vimsupport
from ycm import utils
from ycm.completers.all.omni_completer import OmniCompleter
from ycm.completers.general import syntax_parse
from ycm.client.base_request import BaseRequest
from ycm.client.command_request import SendCommandRequest
from ycm.client.completion_request import CompletionRequest
from ycm.client.event_notification import SendEventNotificationAsync

SERVER_PORT_RANGE_START = 10000

class YouCompleteMe( object ):
  def __init__( self, user_options ):
    self._user_options = user_options
    self._omnicomp = OmniCompleter( user_options )
    self._current_completion_request = None
    self._server_stdout = None
    self._server_stderr = None
    self._server_popen = None
    self._filetypes_with_keywords_loaded = set()
    self._options_thread = None
    self._SetupServer()


  def _SetupServer( self ):
    server_port = SERVER_PORT_RANGE_START + os.getpid()
    command = ''.join( [ 'python ',
                        _PathToServerScript(),
                        ' --port=',
                        str( server_port ),
                        ' --log=',
                        self._user_options[ 'server_log_level' ] ] )

    BaseRequest.server_location = 'http://localhost:' + str( server_port )

    if self._user_options[ 'server_use_vim_stdout' ]:
      self._server_popen = subprocess.Popen( command, shell = True )
    else:
      filename_format = os.path.join( utils.PathToTempDir(),
                                      'server_{port}_{std}.log' )

      self._server_stdout = filename_format.format( port = server_port,
                                                    std = 'stdout' )
      self._server_stderr = filename_format.format( port = server_port,
                                                    std = 'stderr' )

      with open( self._server_stderr, 'w' ) as fstderr:
        with open( self._server_stdout, 'w' ) as fstdout:
          self._server_popen = subprocess.Popen( command,
                                                 stdout = fstdout,
                                                 stderr = fstderr,
                                                 shell = True )

    self._StartOptionsThread()


  def _StartOptionsThread( self ):
    def OptionsThreadMain( options ):
      @retries( 5, delay = 0.5 )
      def PostOptionsToServer():
        BaseRequest.PostDataToHandler( options, 'user_options' )

      PostOptionsToServer()

    self._options_thread = threading.Thread(
        target = OptionsThreadMain,
        args = ( dict( self._user_options ), ) )

    self._options_thread.daemon = True
    self._options_thread.start()



  def CreateCompletionRequest( self ):
    # We have to store a reference to the newly created CompletionRequest
    # because VimScript can't store a reference to a Python object across
    # function calls... Thus we need to keep this request somewhere.
    self._current_completion_request = CompletionRequest()
    return self._current_completion_request


  def SendCommandRequest( self, arguments, completer ):
    return SendCommandRequest( arguments, completer )


  def GetCurrentCompletionRequest( self ):
    return self._current_completion_request


  def GetOmniCompleter( self ):
    return self._omnicomp


  def NativeFiletypeCompletionAvailable( self ):
    # TODO: Talk to server about this.
    return False


  # TODO: This may not be needed at all when the server is ready. Evaluate this
  # later.
  # def FiletypeCompletionAvailable( self ):
  #   return bool( self.GetFiletypeCompleter() )


  def NativeFiletypeCompletionUsable( self ):
    return ( self.CurrentFiletypeCompletionEnabled() and
             self.NativeFiletypeCompletionAvailable() )


  # TODO: This may not be needed at all when the server is ready. Evaluate this
  # later.
  # def FiletypeCompletionUsable( self ):
  #   return ( self.CurrentFiletypeCompletionEnabled() and
  #            self.FiletypeCompletionAvailable() )


  def OnFileReadyToParse( self ):
    extra_data = {}
    if self._user_options[ 'collect_identifiers_from_tags_files' ]:
      extra_data[ 'tag_files' ] = _GetTagFiles()

    if self._user_options[ 'seed_identifiers_with_syntax' ]:
      self._AddSyntaxDataIfNeeded( extra_data )

    SendEventNotificationAsync( 'FileReadyToParse', extra_data )


  def OnBufferUnload( self, deleted_buffer_file ):
    SendEventNotificationAsync( 'BufferUnload',
                                { 'unloaded_buffer': deleted_buffer_file } )


  def OnBufferVisit( self ):
    SendEventNotificationAsync( 'BufferVisit' )


  def OnInsertLeave( self ):
    SendEventNotificationAsync( 'InsertLeave' )


  def OnVimLeave( self ):
    self._server_popen.terminate()


  def OnCurrentIdentifierFinished( self ):
    SendEventNotificationAsync( 'CurrentIdentifierFinished' )


  # TODO: Make this work again.
  def DiagnosticsForCurrentFileReady( self ):
    # if self.FiletypeCompletionUsable():
    #   return self.GetFiletypeCompleter().DiagnosticsForCurrentFileReady()
    return False


  # TODO: Make this work again.
  def GetDiagnosticsForCurrentFile( self ):
    # if self.FiletypeCompletionUsable():
    #   return self.GetFiletypeCompleter().GetDiagnosticsForCurrentFile()
    return []


  # TODO: Make this work again.
  def GetDetailedDiagnostic( self ):
    # if self.FiletypeCompletionUsable():
    #   return self.GetFiletypeCompleter().GetDetailedDiagnostic()
    pass


  # TODO: Make this work again.
  def GettingCompletions( self ):
    # if self.FiletypeCompletionUsable():
    #   return self.GetFiletypeCompleter().GettingCompletions()
    return False


  def DebugInfo( self ):
    completers = set( self._filetype_completers.values() )
    completers.add( self._gencomp )
    output = []
    for completer in completers:
      if not completer:
        continue
      debug = completer.DebugInfo()
      if debug:
        output.append( debug )

    has_clang_support = ycm_core.HasClangSupport()
    output.append( 'Has Clang support compiled in: {0}'.format(
      has_clang_support ) )

    if has_clang_support:
      output.append( ycm_core.ClangVersion() )

    return '\n'.join( output )


  def CurrentFiletypeCompletionEnabled( self ):
    filetypes = vimsupport.CurrentFiletypes()
    filetype_to_disable = self._user_options[
      'filetype_specific_completion_to_disable' ]
    return not all([ x in filetype_to_disable for x in filetypes ])


  def _AddSyntaxDataIfNeeded( self, extra_data ):
    filetype = vimsupport.CurrentFiletypes()[ 0 ]
    if filetype in self._filetypes_with_keywords_loaded:
      return

    self._filetypes_with_keywords_loaded.add( filetype )
    extra_data[ 'syntax_keywords' ] = list(
       syntax_parse.SyntaxKeywordsForCurrentBuffer() )


def _GetTagFiles():
  tag_files = vim.eval( 'tagfiles()' )
  current_working_directory = os.getcwd()
  return [ os.path.join( current_working_directory, x ) for x in tag_files ]


def _PathToServerScript():
  dir_of_current_script = os.path.dirname( os.path.abspath( __file__ ) )
  return os.path.join( dir_of_current_script, 'server/server.py' )

